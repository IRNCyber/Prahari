"""deploy_staging tool for Prahari, backed by the Render API.

Place at: prahari/verifier/render_staging.py

Config (.env):
    DEPLOYMENT_PROVIDER=render
    DEPLOYMENT_TOKEN=<Render API key: Account Settings > API Keys>
    RENDER_STAGING_SERVICE_ID=<srv-xxxx, from the staging service URL or Settings>
    STAGING_BASE_URL=https://prahari-staging.onrender.com
    PRODUCTION_BASE_URL=http://localhost:8000

Flow: guard -> point the staging service at the agent's branch -> trigger a deploy
of that commit -> poll until "live" -> wait for /health -> return a result for replay_traffic.

Check field names against Render's API docs (api-docs.render.com) when you build,
since APIs change. Run a manual test first:  python -m prahari.verifier.render_staging main
"""
from __future__ import annotations

import os
import sys
import time

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

API = "https://api.render.com/v1"
DONE_OK = {"live"}
DONE_FAIL = {"build_failed", "update_failed", "pre_deploy_failed", "canceled", "deactivated"}


class StagingError(RuntimeError):
    pass


def _env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise StagingError(f"{name} is not set in .env")
    return val


def _guard() -> None:
    """The agent must never deploy or replay against production."""
    staging = _env("STAGING_BASE_URL").rstrip("/")
    prod = os.getenv("PRODUCTION_BASE_URL", "").rstrip("/")
    if staging == prod:
        raise StagingError("Staging and production URLs are identical; refusing to continue.")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_env('DEPLOYMENT_TOKEN')}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _wait_for_deploy(service_id: str, deploy_id: str, timeout: int = 600) -> str:
    deadline = time.time() + timeout
    status = "created"
    while time.time() < deadline:
        r = httpx.get(f"{API}/services/{service_id}/deploys/{deploy_id}", headers=_headers(), timeout=20)
        r.raise_for_status()
        status = r.json().get("status", status)
        if status in DONE_OK:
            return status
        if status in DONE_FAIL:
            raise StagingError(f"Render deploy ended with status '{status}'. Check the build logs in Render.")
        time.sleep(10)
    raise StagingError(f"Timed out waiting for deploy (last status '{status}').")


def _wait_for_health(base_url: str, timeout: int = 180) -> None:
    """Free instances sleep; keep trying /health until the app answers 200."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=10).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(5)
    raise StagingError("Staging did not become healthy in time.")


def deploy_staging(branch: str, commit_sha: str | None = None) -> dict:
    """Deploy the agent's patch branch to the staging service and wait until healthy."""
    _guard()
    if os.getenv("DEPLOYMENT_PROVIDER", "") != "render":
        raise StagingError("DEPLOYMENT_PROVIDER must be 'render' for this module.")
    service_id = _env("RENDER_STAGING_SERVICE_ID")
    base_url = _env("STAGING_BASE_URL").rstrip("/")
    started = time.time()

    # 1) Make staging track the branch the agent pushed (never main in production sense:
    #    this service is staging only).
    r = httpx.patch(f"{API}/services/{service_id}", headers=_headers(), json={"branch": branch}, timeout=30)
    r.raise_for_status()

    # 2) Trigger a deploy, pinned to a commit when we know it.
    body: dict = {"clearCache": "do_not_clear"}
    if commit_sha:
        body["commitId"] = commit_sha
    r = httpx.post(f"{API}/services/{service_id}/deploys", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    deploy_id = r.json()["id"]

    # 3) Wait for the build, then for the app itself.
    _wait_for_deploy(service_id, deploy_id)
    _wait_for_health(base_url)

    return {
        "ok": True,
        "branch": branch,
        "deploy_id": deploy_id,
        "staging_url": base_url,
        "seconds": round(time.time() - started),
    }


if __name__ == "__main__":
    try:
        print(deploy_staging(sys.argv[1] if len(sys.argv) > 1 else "main"))
    except StagingError as e:
        print(f"Staging error: {e}")
        sys.exit(1)
    except httpx.HTTPError as e:
        print(f"HTTP error talking to Render: {e}")
        sys.exit(2)
