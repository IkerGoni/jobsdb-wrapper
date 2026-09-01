"""SQLite-backed job detail cache — dedupe between runs, incremental crawls."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


class DetailCache:
    """Tiny sqlite cache for full job payloads.

    Schema: details(job_id, market, content_hash, payload, fetched_at)
    """

    def __init__(self, path: str | Path):
        self.path = str(Path(path).expanduser())
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS details (
                 job_id TEXT NOT NULL,
                 market TEXT NOT NULL,
                 content_hash TEXT,
                 payload TEXT,
                 fetched_at REAL,
                 PRIMARY KEY (job_id, market)
               )"""
        )
        self._conn.commit()

    @staticmethod
    def content_hash(payload: dict) -> str:
        raw = json.dumps(payload.get("content") or "", sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()

    def get(self, job_id: str, market: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM details WHERE job_id=? AND market=?",
                (str(job_id), market),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def get_valid(self, job_id: str, market: str) -> dict | None:
        """Return cached payload only if its stored hash still matches content."""
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, content_hash FROM details WHERE job_id=? AND market=?",
                (str(job_id), market),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
        except Exception:
            return None
        if row[1] != self.content_hash(payload):
            return None
        return payload

    def put(self, job_id: str, market: str, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO details VALUES (?,?,?,?,?)",
                (
                    str(job_id),
                    market,
                    self.content_hash(payload),
                    json.dumps(payload, ensure_ascii=False),
                    time.time(),
                ),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            n, markets = self._conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT market) FROM details"
            ).fetchone()
        return {"entries": n, "markets": markets}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
