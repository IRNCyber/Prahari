"""Authenticated GitHub deploy-event ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import HTTPException, Request

from agent.loop import run as investigate
from prahari.store import audit, record_alert, record_deployment


def _validate_payload_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1_000_000:
                raise HTTPException(status_code=413, detail="Webhook payload is too large.")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid webhook content length.") from error


async def _read_json_object(request: Request) -> dict[str, Any]:
    _validate_payload_size(request)
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object.")
    return payload


def _configured_repository() -> str:
    value = os.getenv("GITHUB_REPOSITORY", "").strip()
    value = value.removesuffix(".git").rstrip("/")
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    return value.lower()


async def handle_github_webhook(request: Request) -> dict[str, Any]:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="GitHub webhook secret is not configured.")
    _validate_payload_size(request)
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    supplied = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object.")

    repository_data = payload.get("repository")
    if not isinstance(repository_data, dict):
        raise HTTPException(status_code=400, detail="Webhook repository metadata is missing.")
    repository = str(repository_data.get("full_name", "")).lower()
    configured = _configured_repository()
    if not configured or repository != configured:
        raise HTTPException(status_code=403, detail="Webhook repository is not configured for this service.")
    event = request.headers.get("x-github-event", "")
    if event != "deployment_status":
        return {"accepted": False, "reason": "event_not_supported", "event": event}

    deployment = payload.get("deployment")
    status = payload.get("deployment_status")
    if not isinstance(deployment, dict) or not isinstance(status, dict):
        raise HTTPException(status_code=400, detail="Deployment status metadata is missing.")
    state = str(status.get("state", "unknown"))
    revision = str(deployment.get("sha", "unknown"))
    environment = str(deployment.get("environment", "unknown"))
    target_url = status.get("target_url")
    evidence = [f"repository:{repository}", f"revision:{revision}", f"deployment_status:{state}"]
    record_deployment("github", repository, revision, environment, state, str(target_url) if target_url else None)
    audit("github_deployment_webhook", {"repository": repository, "revision": revision, "state": state}, actor="github")
    if state not in {"failure", "error"}:
        return {"accepted": True, "alert": None, "triggered": False, "investigation": None}
    stored, new_alert = record_alert(
        fingerprint=f"github-deployment:{repository}:{revision}:{state}",
        severity="high",
        summary=f"GitHub deployment {state}: {revision[:12]}",
        evidence=evidence,
    )
    investigation = await __import__("asyncio").to_thread(investigate, {"type": "deployment_status", "evidence": evidence}) if new_alert else None
    return {"accepted": True, "alert": stored, "triggered": new_alert, "investigation": investigation}


async def handle_gitlab_webhook(request: Request) -> dict[str, Any]:
    secret = os.getenv("GITLAB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="GitLab webhook secret is not configured.")
    supplied = request.headers.get("x-gitlab-token", "")
    if not hmac.compare_digest(supplied, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook token.")
    payload = await _read_json_object(request)
    if request.headers.get("x-gitlab-event") != "Deployment Hook":
        return {"accepted": False, "reason": "event_not_supported"}

    project = payload.get("project")
    if not isinstance(project, dict):
        raise HTTPException(status_code=400, detail="Webhook project metadata is missing.")
    repository = str(project.get("path_with_namespace", "")).lower()
    configured = _configured_repository()
    if not configured or repository != configured:
        raise HTTPException(status_code=403, detail="Webhook repository is not configured for this service.")

    status_data = payload.get("deployment_status")
    status_data = status_data if isinstance(status_data, dict) else {}
    commit = payload.get("commit")
    commit = commit if isinstance(commit, dict) else {}
    state = str(status_data.get("status", payload.get("status", "unknown"))).lower()
    revision = str(payload.get("sha", commit.get("id", "unknown")))
    environment = str(payload.get("environment", payload.get("environment_name", "unknown")))
    target_url = payload.get("environment_url", payload.get("deployment_url"))
    evidence = [f"repository:{repository}", f"revision:{revision}", f"deployment_status:{state}"]
    record_deployment("gitlab", repository, revision, environment, state, str(target_url) if target_url else None)
    audit("gitlab_deployment_webhook", {"repository": repository, "revision": revision, "state": state}, actor="gitlab")
    if state not in {"failed", "failure", "error"}:
        return {"accepted": True, "alert": None, "triggered": False, "investigation": None}
    stored, new_alert = record_alert(
        fingerprint=f"gitlab-deployment:{repository}:{revision}:{state}",
        severity="high",
        summary=f"GitLab deployment {state}: {revision[:12]}",
        evidence=evidence,
    )
    investigation = await __import__("asyncio").to_thread(investigate, {"type": "deployment_status", "evidence": evidence}) if new_alert else None
    return {"accepted": True, "alert": stored, "triggered": new_alert, "investigation": investigation}
