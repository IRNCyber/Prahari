"""Deployment contract; disabled unless explicit credentials are configured."""

from __future__ import annotations

import os

from agent.integrations.koyeb import KoyebClient, KoyebConfig
from agent.integrations.render import RenderClient, RenderConfig


class DeploymentClient:
    def readiness(self) -> dict[str, object]:
        provider = os.getenv("DEPLOYMENT_PROVIDER", "")
        render = RenderConfig.from_environment()
        koyeb = KoyebConfig.from_environment()
        enabled = (provider == "render" and bool(render.api_key and render.staging_service_id and render.production_service_id)) or (provider == "koyeb" and bool(koyeb.api_token and koyeb.staging_service_id and koyeb.production_service_id))
        return {"provider": provider, "staging": bool(os.getenv("STAGING_BASE_URL")), "production": bool(os.getenv("PRODUCTION_BASE_URL")), "enabled": enabled}

    def deploy(self, environment: str, revision: str) -> dict[str, object]:
        if not self.readiness()["enabled"]:
            raise RuntimeError("Render deployment requires its API key and staging/production service IDs.")
        if os.getenv("DEPLOYMENT_PROVIDER") == "koyeb":
            return KoyebClient(KoyebConfig.from_environment()).redeploy(environment)
        return RenderClient(RenderConfig.from_environment()).deploy(environment, revision)
