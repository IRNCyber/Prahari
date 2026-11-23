"""Koyeb API adapter for read-only status and explicit service redeploys."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class KoyebConfig:
    api_token: str
    staging_service_id: str
    production_service_id: str

    @classmethod
    def from_environment(cls) -> KoyebConfig:
        return cls(os.getenv("KOYEB_API_TOKEN", ""), os.getenv("KOYEB_STAGING_SERVICE_ID", ""), os.getenv("KOYEB_PRODUCTION_SERVICE_ID", ""))


class KoyebClient:
    def __init__(self, config: KoyebConfig) -> None:
        if not config.api_token:
            raise RuntimeError("KOYEB_API_TOKEN is required.")
        self.config = config
        self.client = httpx.Client(base_url="https://app.koyeb.com/v1", headers={"Accept": "application/json", "Authorization": f"Bearer {config.api_token}"}, timeout=20)

    def validate(self) -> dict[str, object]:
        response = self.client.get("/services", params={"limit": 1})
        response.raise_for_status()
        return {"authenticated": True, "services_readable": True}

    def service(self, service_id: str) -> dict[str, Any]:
        response = self.client.get(f"/services/{service_id}")
        response.raise_for_status()
        return response.json()

    def redeploy(self, environment: str) -> dict[str, Any]:
        service_id = self.config.staging_service_id if environment == "staging" else self.config.production_service_id
        if not service_id:
            raise RuntimeError(f"KOYEB_{environment.upper()}_SERVICE_ID is required.")
        response = self.client.post(f"/services/{service_id}/redeploy")
        response.raise_for_status()
        return response.json()


def platform_status() -> dict[str, object]:
    """Read Koyeb's public status page without requiring user credentials."""
    with httpx.Client(base_url="https://status.koyeb.com/v3", timeout=15) as client:
        summary = client.get("/summary.json")
        summary.raise_for_status()
        components = client.get("/components.json")
        components.raise_for_status()
    data = summary.json()
    return {
        "provider": "koyeb",
        "status": data.get("page", {}).get("status", "UNKNOWN"),
        "active_incidents": len(data.get("activeIncidents", [])),
        "active_maintenances": len(data.get("activeMaintenances", [])),
        "components": [{"name": component.get("name"), "status": component.get("status")} for component in components.json().get("components", [])],
    }
