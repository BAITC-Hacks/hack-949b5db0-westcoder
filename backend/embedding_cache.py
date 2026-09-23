"""Short SQLite transactions. No connection is held during a network call."""
from contextlib import contextmanager, closing
import json
from pathlib import Path
import sqlite3


class EmbeddingCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    @contextmanager
    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.directory / "embeddings.sqlite3", timeout=1)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS decisions (key TEXT PRIMARY KEY, value TEXT)")
            yield db

    def decision(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM decisions WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def vectors(self, keys):
        with self.connect() as db:
            return {key: row[0] for key in keys
                    if (row := db.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone())}

    def save(self, key, scores, mode, vectors):
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                           [(k, json.dumps(v, allow_nan=False)) for k, v in vectors.items()])
            db.execute("INSERT OR REPLACE INTO decisions VALUES (?, ?)",
                       (key, json.dumps({"scores": scores, "mode": mode}, allow_nan=False)))
