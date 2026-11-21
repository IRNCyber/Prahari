"""Deployment contract; disabled unless explicit credentials are configured."""

from __future__ import annotations

import os

from agent.integrations.render import RenderClient, RenderConfig


class DeploymentClient:
    def readiness(self) -> dict[str, object]:
        config = RenderConfig.from_environment()
        enabled = os.getenv("DEPLOYMENT_PROVIDER") == "render" and bool(config.api_key and config.staging_service_id and config.production_service_id)
        return {"provider": os.getenv("DEPLOYMENT_PROVIDER", ""), "staging": bool(os.getenv("STAGING_BASE_URL")), "production": bool(os.getenv("PRODUCTION_BASE_URL")), "enabled": enabled}

    def deploy(self, environment: str, revision: str) -> dict[str, object]:
        if not self.readiness()["enabled"]:
            raise RuntimeError("Render deployment requires its API key and staging/production service IDs.")
        return RenderClient(RenderConfig.from_environment()).deploy(environment, revision)
