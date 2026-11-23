"""Render API client used for status and explicitly requested deployments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class RenderConfig:
    api_key: str
    staging_service_id: str
    production_service_id: str

    @classmethod
    def from_environment(cls) -> RenderConfig:
        return cls(os.getenv("RENDER_API_KEY", ""), os.getenv("RENDER_STAGING_SERVICE_ID", ""), os.getenv("RENDER_PRODUCTION_SERVICE_ID", ""))


class RenderClient:
    def __init__(self, config: RenderConfig) -> None:
        if not config.api_key:
            raise RuntimeError("RENDER_API_KEY is required.")
        self.config = config
        self.client = httpx.Client(base_url="https://api.render.com/v1", headers={"Accept": "application/json", "Authorization": f"Bearer {config.api_key}"}, timeout=20)

    def validate(self) -> dict[str, object]:
        response = self.client.get("/services", params={"limit": 1})
        response.raise_for_status()
        return {"authenticated": True, "services_readable": True}

    def deploy(self, environment: str, commit_id: str | None = None) -> dict[str, Any]:
        service_id = self.config.staging_service_id if environment == "staging" else self.config.production_service_id
        if not service_id:
            raise RuntimeError(f"RENDER_{environment.upper()}_SERVICE_ID is required.")
        payload: dict[str, str] = {"deployMode": "build_and_deploy"}
        if commit_id:
            payload["commitId"] = commit_id
        response = self.client.post(f"/services/{service_id}/deploys", json=payload)
        response.raise_for_status()
        return response.json()
