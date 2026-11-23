"""Environment-backed configuration with local .env support."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def load_environment() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(path, override=False)


def validate_environment() -> None:
    if os.getenv("PRAHARI_ENV", "development").lower() != "production":
        return
    missing = [
        key
        for key in ("AUTH_ISSUER_URL", "AUTH_AUDIENCE", "PRAHARI_APPROVER_TOKEN")
        if not os.getenv(key, "").strip()
    ]
    provider = os.getenv("AUTH_PROVIDER", "none").lower()
    if provider != "auth0":
        missing.append("AUTH_PROVIDER=auth0")
    elif not all(
        os.getenv(key, "").strip() for key in ("AUTH_ISSUER_URL", "AUTH_AUDIENCE")
    ):
        missing.append("AUTH_ISSUER_URL and AUTH_AUDIENCE for Auth0")
    if len(os.getenv("PRAHARI_APPROVER_TOKEN", "")) < 32:
        missing.append("PRAHARI_APPROVER_TOKEN (at least 32 characters)")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        missing.append("a PostgreSQL DATABASE_URL")
    else:
        database_password = urlsplit(database_url).password
        if not database_password or database_password == "prahari":
            missing.append("a non-default PostgreSQL password")
    if missing:
        raise RuntimeError(f"Production configuration is incomplete: {', '.join(dict.fromkeys(missing))}.")


load_environment()
