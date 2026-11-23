"""Configured dependency probes with bounded timeouts and no redirect following."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from agent.quality.planner import retry_delay

ROOT = Path(__file__).resolve().parents[1]


def check_dependencies() -> list[dict[str, Any]]:
    config_path = ROOT / "deps.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    results = []
    with httpx.Client(follow_redirects=False) as client:
        for dependency in config.get("dependencies", []):
            name, url = str(dependency["name"]), str(dependency["url"])
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"Dependency {name} has a non-HTTP URL.")
            timeout = min(max(float(dependency.get("timeout_seconds", 3)), 0.1), 10)
            try:
                response = client.get(url, timeout=timeout)
            except httpx.HTTPError as error:
                results.append({
                    "name": name,
                    "healthy": False,
                    "error": type(error).__name__,
                    "retry_after_seconds": retry_delay(1, transient=True, idempotent=True),
                    "circuit_breaker_recommended": True,
                })
                continue
            retryable = response.status_code >= 500
            results.append({
                "name": name,
                "healthy": response.is_success,
                "status_code": response.status_code,
                "retry_after_seconds": retry_delay(1, transient=retryable, idempotent=True),
                "circuit_breaker_recommended": retryable,
            })
    return results
