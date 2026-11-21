"""Approval authentication gate; replace with provider-specific JWT verification in deployment."""

from __future__ import annotations

import os
import secrets

import httpx


def authorise_approval(token: str | None) -> bool:
    expected = os.getenv("PRAHARI_APPROVER_TOKEN", "")
    return bool(expected and token and secrets.compare_digest(expected, token))


def provider_status() -> dict[str, object]:
    return {"provider": os.getenv("AUTH_PROVIDER", "local-token"), "issuer_configured": bool(os.getenv("AUTH_ISSUER_URL")), "audience_configured": bool(os.getenv("AUTH_AUDIENCE"))}


def discover_provider() -> dict[str, object]:
    issuer = os.getenv("AUTH_ISSUER_URL", "").rstrip("/")
    if not issuer:
        raise RuntimeError("AUTH_ISSUER_URL is not configured.")
    response = httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=15)
    response.raise_for_status()
    data = response.json()
    return {"discovered": True, "issuer": data.get("issuer"), "jwks_uri": bool(data.get("jwks_uri"))}
