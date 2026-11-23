"""Opt-in Loki log push client for redacted Prahari audit events."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from prahari.store import _redact


class LokiClient:
    def __init__(
        self,
        url: str | None = None,
        tenant_id: str | None = None,
        bearer_token: str | None = None,
    ) -> None:
        self.url = url if url is not None else os.getenv("LOKI_URL", "")
        self.tenant_id = tenant_id if tenant_id is not None else os.getenv("LOKI_TENANT_ID", "")
        self.bearer_token = bearer_token if bearer_token is not None else os.getenv("LOKI_BEARER_TOKEN", "")

    def configured(self) -> bool:
        parsed = urlparse(self.url)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)

    def send(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.configured():
            raise RuntimeError("LOKI_URL must be an HTTP(S) URL.")
        headers = {}
        if self.tenant_id:
            headers["X-Scope-OrgID"] = self.tenant_id
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        body = {
            "streams": [{
                "stream": {"service_name": "prahari", "event_type": event_type},
                "values": [[str(time.time_ns()), json.dumps(_redact(payload), default=str)]],
            }],
        }
        response = httpx.post(f"{self.url.rstrip('/')}/loki/api/v1/push", json=body, headers=headers, timeout=10)
        response.raise_for_status()
