"""Postgres readiness adapter; database schema remains owned by migrations."""

from __future__ import annotations

import os

import psycopg


def postgres_configured() -> bool:
    url = os.getenv("POSTGRES_URL", os.getenv("DATABASE_URL", ""))
    return url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))


def validate_postgres() -> dict[str, object]:
    url = os.getenv("POSTGRES_URL", os.getenv("DATABASE_URL", ""))
    if not postgres_configured():
        raise RuntimeError("POSTGRES_URL is not configured.")
    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, connect_timeout=10, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), version()")
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL readiness query returned no result.")
        database, version = row
    return {"connected": True, "database": database, "server": str(version).split(" ", 2)[:2]}
