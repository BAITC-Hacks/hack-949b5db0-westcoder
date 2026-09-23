"""Optional real embeddings, persistent cache and explicit offline fallback."""
import hashlib
from contextlib import contextmanager
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from urllib.request import Request, urlopen
from .models import finite_number
from .embedding_cache import EmbeddingCache


def validate_vector(vector):
    if not isinstance(vector, list) or not vector or not all(finite_number(v) for v in vector):
        raise ValueError("Invalid embedding")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Invalid embedding norm")
    return norm


def cosine(left, right):
    if not left or len(left) != len(right):
        raise ValueError("Incompatible embedding dimensions")
    left_norm, right_norm = validate_vector(left), validate_vector(right)
    return max(0.0, min(1.0, math.fsum((a/left_norm)*(b/right_norm) for a,b in zip(left,right))))


def cached_decision(raw, candidates):
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Invalid cached decision")
    scores, mode = result.get("scores"), result.get("mode")
    if mode == "unavailable" and scores is None:
        return None, mode
    if (mode != "embeddings" or not isinstance(scores, dict)
            or set(scores) != {c.id for c in candidates}
            or any(not finite_number(v) or not 0 <= v <= 1 for v in scores.values())):
        raise ValueError("Incomplete or invalid semantic scores")
    return scores, mode


def semantic_query(event):
    if event.preferences:
        return f"{event.category}. Формат: {event.event_format}. Пожелания: {event.preferences}"
    parts = [event.category, event.city, f"Формат: {event.event_format}",
             f"Бюджет: {event.budget_kzt} тенге", f"Дата: {event.date}"]
    if event.duration_hours is not None:
        parts.append(f"Длительность: {event.duration_hours} часов")
    if event.language:
        parts.append(f"Язык: {event.language}")
    return ". ".join(parts)


class SemanticMatcher:
    def __init__(self, cache_dir, enabled=False, api_key=None, model=None):
        self.enabled = enabled
        self.key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.cache_dir = Path(cache_dir)
        self.cache = EmbeddingCache(cache_dir)
        self._guard = threading.Lock()
        self._requests = {}

    @contextmanager
    def _request_lock(self, key):
        # Only identical requests share a lock. Cached/unrelated queries never
        # wait for another query's provider call. Remove idle locks to bound memory.
        with self._guard:
            entry = self._requests.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._requests[key]

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

    def similarities(self, event, candidates, fingerprint, refresh=False):
        if not candidates:
            return None, "not_needed"
        if not self.enabled:
            return None, "disabled"
        query = semantic_query(event)
        identity = json.dumps(["v3", self.model, fingerprint, asdict(event), sorted(c.id for c in candidates)],
                              ensure_ascii=False, sort_keys=True, allow_nan=False)
        decision_key = hashlib.sha256(identity.encode()).hexdigest()
        # Keep ordinary repeats stable. Explicit refresh can replace a failed
        # snapshot; successful snapshots never need another provider call.
        with self._request_lock(decision_key):
            try:
                saved = self.cache.decision(decision_key)
                if saved:
                    try:
                        scores, mode = cached_decision(saved, candidates)
                    except (ValueError, TypeError, RecursionError):
                        if not refresh:
                            return None, "cache_unavailable"
                    else:
                        if mode == "embeddings" or not refresh:
                            return scores, mode
                if not self.key:
                    return None, "missing_key"
                texts = [query] + [c.description or "Описание не указано" for c in candidates]
                keys = [hashlib.sha256((self.model + "\0" + t).encode()).hexdigest() for t in texts]
                stored = self.cache.vectors(keys)
                vectors, missing = {}, {}
                for key, value in zip(keys, texts):
                    if key in stored:
                        try:
                            vector = json.loads(stored[key])
                            validate_vector(vector)
                            vectors[key] = vector
                            continue
                        except (ValueError, TypeError, RecursionError):
                            pass  # Rebuild only malformed vectors; never trust them.
                    missing[key] = value
                fresh_vectors = {}
                try:
                    if missing:
                        embeddings = self._embed(list(missing.values()))
                        if len(embeddings) != len(missing):
                            raise ValueError("Incomplete embedding batch")
                        for key, vector in zip(missing, embeddings):
                            validate_vector(vector)
                            fresh_vectors[key] = vector
                        vectors.update(fresh_vectors)
                    scores = {c.id: cosine(vectors[keys[0]], vectors[key]) for c, key in zip(candidates, keys[1:])}
                    mode = "embeddings"
                except Exception:
                    # Never expose tokens, upstream errors or partial rankings.
                    scores, mode, fresh_vectors = None, "unavailable", {}
                self.cache.save(decision_key, scores, mode, fresh_vectors)
                return scores, mode
            except (OSError, sqlite3.Error, ValueError, RecursionError):
                return None, "cache_unavailable"
