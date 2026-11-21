"""Minimal Sentry event sender used for incident reporting."""

from __future__ import annotations

import json
import os
import uuid
from urllib.parse import urlparse

import httpx


class SentryClient:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("SENTRY_DSN", "")

    def configured(self) -> bool:
        return self.dsn.startswith(("http://", "https://"))

    def capture_incident(self, title: str, context: dict[str, object]) -> None:
        if not self.configured():
            raise RuntimeError("SENTRY_DSN is not configured.")
        parsed = urlparse(self.dsn)
        public_key = parsed.username
        project = parsed.path.strip("/")
        endpoint = f"{parsed.scheme}://{parsed.hostname}/api/{project}/store/"
        payload = {"event_id": uuid.uuid4().hex, "message": title, "level": "error", "extra": context}
        response = httpx.post(endpoint, content=json.dumps(payload), headers={"X-Sentry-Auth": f"Sentry sentry_version=7, sentry_key={public_key}"}, timeout=15)
        response.raise_for_status()
