"""Minimal Sentry event sender used for incident reporting."""

from __future__ import annotations

import json
import os
import uuid
from urllib.parse import urlparse

import httpx

from prahari.store import _redact


class SentryClient:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn if dsn is not None else os.getenv("SENTRY_DSN", "")

    def configured(self) -> bool:
        parsed = urlparse(self.dsn)
        return parsed.scheme in {"http", "https"} and bool(parsed.username and parsed.hostname and parsed.path.strip("/"))

    def capture_incident(self, title: str, context: dict[str, object]) -> None:
        if not self.configured():
            raise RuntimeError("SENTRY_DSN is not configured.")
        parsed = urlparse(self.dsn)
        public_key = parsed.username
        project = parsed.path.strip("/")
        if not public_key or not parsed.hostname or not project:
            raise RuntimeError("SENTRY_DSN must include a public key, host, and project.")
        endpoint = f"{parsed.scheme}://{parsed.hostname}/api/{project}/store/"
        payload = {"event_id": uuid.uuid4().hex, "message": str(_redact(title)), "level": "error", "extra": _redact(context)}
        response = httpx.post(endpoint, content=json.dumps(payload), headers={"X-Sentry-Auth": f"Sentry sentry_version=7, sentry_key={public_key}"}, timeout=15)
        response.raise_for_status()
