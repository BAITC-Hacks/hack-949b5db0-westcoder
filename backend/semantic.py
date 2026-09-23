"""Optional real embeddings, persistent cache and explicit offline fallback."""
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from urllib.request import Request, urlopen


def cosine(left, right):
    if not left or len(left) != len(right):
        raise ValueError("Incompatible embedding dimensions")
    denominator = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    if not denominator:
        raise ValueError("Zero embedding vector")
    return max(0.0, min(1.0, sum(a*b for a, b in zip(left, right)) / denominator))


def semantic_query(event):
    parts = [event.category, event.city, f"Формат: {event.event_format}",
             f"Бюджет: {event.budget_kzt:g} тенге", f"Дата: {event.date}"]
    if event.duration_hours is not None:
        parts.append(f"Длительность: {event.duration_hours:g} часов")
    if event.language:
        parts.append(f"Язык: {event.language}")
    return ". ".join(parts)


class SemanticMatcher:
    def __init__(self, cache_dir, enabled=False, api_key=None, model=None):
        self.enabled = enabled
        self.key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.cache_dir = Path(cache_dir)
        self.lock = threading.Lock()

    def _embed(self, texts):
        payload = json.dumps({"model": self.model, "input": texts, "encoding_format": "float"}).encode()
        request = Request("https://api.openai.com/v1/embeddings", data=payload, headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        with urlopen(request, timeout=6) as response:
            data = json.load(response)
        rows = data.get("data", [])
        if len(rows) != len(texts) or {r.get("index") for r in rows} != set(range(len(texts))):
            raise ValueError("Incomplete embeddings response")
        return [row["embedding"] for row in sorted(rows, key=lambda r: r["index"])]

    def similarities(self, event, candidates, fingerprint):
        if not candidates:
            return None, "not_needed"
        if not self.enabled:
            return None, "disabled"
        query = semantic_query(event)
        identity = json.dumps([self.model, fingerprint, query], ensure_ascii=False)
        decision_key = hashlib.sha256(identity.encode()).hexdigest()
        # Decisions (including API failures) persist so repeated requests keep order.
        with self.lock:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.cache_dir / "embeddings.sqlite3") as db:
                    db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value TEXT)")
                    db.execute("CREATE TABLE IF NOT EXISTS decisions (key TEXT PRIMARY KEY, value TEXT)")
                    saved = db.execute("SELECT value FROM decisions WHERE key=?", (decision_key,)).fetchone()
                    if saved:
                        result = json.loads(saved[0])
                        return result["scores"], result["mode"]
                    scores, mode = None, "missing_key"
                    if self.key:
                        try:
                            texts = [query] + [c.description or "Описание не указано" for c in candidates]
                            keys = [hashlib.sha256((self.model + "\0" + t).encode()).hexdigest() for t in texts]
                            vectors, missing = {}, {}
                            for key, value in zip(keys, texts):
                                cached = db.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone()
                                if cached:
                                    vectors[key] = json.loads(cached[0])
                                else:
                                    missing[key] = value
                            if missing:
                                embeddings = self._embed(list(missing.values()))
                                for key, vector in zip(missing, embeddings):
                                    if not isinstance(vector, list) or not vector or any(
                                        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector
                                    ):
                                        raise ValueError("Invalid embedding")
                                    vectors[key] = vector
                                    db.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?)", (key, json.dumps(vector)))
                            scores = {c.id: cosine(vectors[keys[0]], vectors[key]) for c, key in zip(candidates, keys[1:])}
                            mode = "embeddings"
                        except Exception:
                            # Never expose tokens, upstream errors or partial semantic rankings.
                            scores, mode = None, "unavailable"
                    # A missing key is configuration, not a cached provider failure.
                    if mode != "missing_key":
                        db.execute("INSERT OR REPLACE INTO decisions VALUES (?, ?)",
                                   (decision_key, json.dumps({"scores": scores, "mode": mode})))
                    return scores, mode
            except (OSError, sqlite3.Error, ValueError):
                return None, "cache_unavailable"
