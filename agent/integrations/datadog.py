"""Read-only Datadog telemetry adapter."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class DatadogConfig:
    api_key: str
    app_key: str
    site: str

    @classmethod
    def from_environment(cls) -> "DatadogConfig":
        config = cls(
            api_key=os.getenv("DATADOG_API_KEY", ""),
            app_key=os.getenv("DATADOG_APP_KEY", ""),
            site=os.getenv("DATADOG_SITE", "datadoghq.com"),
        )
        if not all((config.api_key, config.app_key, config.site)):
            raise RuntimeError("DATADOG_API_KEY, DATADOG_APP_KEY, and DATADOG_SITE are required.")
        return config

    @property
    def api_url(self) -> str:
        site = self.site.removeprefix("https://").removeprefix("api.").rstrip("/")
        return f"https://api.{site}"


class DatadogClient:
    def __init__(self, config: DatadogConfig) -> None:
        self.client = httpx.Client(
            base_url=config.api_url,
            headers={"DD-API-KEY": config.api_key, "DD-APPLICATION-KEY": config.app_key},
            timeout=20,
        )

    def validate(self) -> dict[str, object]:
        api_key = self.client.get("/api/v1/validate")
        api_key.raise_for_status()
        metrics = self.client.get("/api/v1/metrics", params={"from": int(time.time()) - 3600})
        metrics.raise_for_status()
        return {"api_key_valid": bool(api_key.json().get("valid")), "metrics_readable": True}

    def query_metrics(self, query: str, start: int, end: int) -> dict[str, Any]:
        response = self.client.get("/api/v1/query", params={"query": query, "from": start, "to": end})
        response.raise_for_status()
        return response.json()

    def search_logs(self, query: str, start_iso: str, end_iso: str, limit: int = 100) -> dict[str, Any]:
        response = self.client.post("/api/v2/logs/events/search", json={
            "filter": {"query": query, "from": start_iso, "to": end_iso},
            "page": {"limit": min(limit, 100)},
            "sort": "timestamp",
        })
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()
