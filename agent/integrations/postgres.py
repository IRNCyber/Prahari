"""Postgres readiness adapter; database schema remains owned by migrations."""

from __future__ import annotations

import os

import psycopg


def postgres_configured() -> bool:
    return os.getenv("POSTGRES_URL", "").startswith(("postgres://", "postgresql://"))


def validate_postgres() -> dict[str, object]:
    url = os.getenv("POSTGRES_URL", "")
    if not postgres_configured():
        raise RuntimeError("POSTGRES_URL is not configured.")
    with psycopg.connect(url, connect_timeout=10, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), version()")
            database, version = cursor.fetchone()
    return {"connected": True, "database": database, "server": str(version).split(" ", 2)[:2]}
