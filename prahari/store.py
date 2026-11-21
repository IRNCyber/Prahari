"""Durable local incident, audit, and shared-state storage."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("PRAHARI_DATA_DIR", ROOT / "data"))
DATABASE_PATH = DATA_DIR / "prahari.db"


def now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    try:
        database.executescript("""
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, scenario TEXT, status TEXT NOT NULL, severity TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, summary TEXT);
            CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, event_type TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        yield database
        database.commit()
    finally:
        database.close()


def get_state() -> dict[str, object]:
    with connection() as database:
        row = database.execute("SELECT value FROM state WHERE key = 'fault'").fetchone()
    return json.loads(row["value"]) if row else {"scenario": None}


def set_state(value: dict[str, object]) -> dict[str, object]:
    with connection() as database:
        database.execute("INSERT INTO state(key, value, updated_at) VALUES ('fault', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (json.dumps(value), now()))
    return value


def audit(event_type: str, payload: dict[str, object], actor: str = "system", incident_id: str | None = None) -> None:
    with connection() as database:
        database.execute("INSERT INTO audit_events(incident_id, event_type, actor, payload, created_at) VALUES (?, ?, ?, ?, ?)", (incident_id, event_type, actor, json.dumps(payload), now()))


def recent_audit(limit: int = 100) -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
