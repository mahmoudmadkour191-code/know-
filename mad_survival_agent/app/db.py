from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,
              level TEXT NOT NULL,
              message TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stats (
              key TEXT PRIMARY KEY,
              value REAL NOT NULL DEFAULT 0
            );
            """
        )
        self.conn.commit()

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def delete(self, key: str) -> None:
        self.conn.execute("DELETE FROM kv WHERE key=?", (key,))
        self.conn.commit()

    def log(self, message: str, level: str = "INFO") -> None:
        self.conn.execute(
            "INSERT INTO events(ts,level,message) VALUES(?,?,?)",
            (time.time(), level, message[:2000]),
        )
        self.conn.commit()

    def recent_events(self, limit: int = 12) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT ts,level,message FROM events ORDER BY id DESC LIMIT ?", (limit,)
            )
        )

    def incr(self, key: str, amount: float = 1) -> None:
        self.conn.execute(
            "INSERT INTO stats(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value",
            (key, amount),
        )
        self.conn.commit()

    def stat(self, key: str, default: float = 0) -> float:
        row = self.conn.execute("SELECT value FROM stats WHERE key=?", (key,)).fetchone()
        return float(row["value"]) if row else default

    def snapshot(self) -> dict[str, Any]:
        try:
            sleep_until = float(self.get("gemini_sleep_until", "0") or "0")
        except ValueError:
            sleep_until = 0.0
        return {
            "cash": self.stat("cash", 0),
            "jobs_found": self.stat("jobs_found", 0),
            "jobs_contacted": self.stat("jobs_contacted", 0),
            "jobs_completed": self.stat("jobs_completed", 0),
            "jobs_failed": self.stat("jobs_failed", 0),
            "messages_sent": self.stat("messages_sent", 0),
            "groups_joined": self.stat("groups_joined", 0),
            "gemini_requests": self.stat("gemini_requests", 0),
            "gemini_tokens_today": self.stat("gemini_tokens_today", 0),
            "gemini_tokens_total": self.stat("gemini_tokens_total", 0),
            "gemini_sleep_until": sleep_until,
        }
