"""Approval authentication gate; replace with provider-specific JWT verification in deployment."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import Cookie, Header, HTTPException, status


@lru_cache(maxsize=1)
def _jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json", cache_jwk_set=True)


def _principal(authorization: str | None) -> dict[str, Any]:
    provider = os.getenv("AUTH_PROVIDER", "none").lower()
    if provider in {"", "none", "local-token"}:
        if os.getenv("PRAHARI_ENV", "development").lower() == "production":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication is required in production.")
        return {"sub": "local-operator", "permissions": ["operator", "approver"]}

    issuer = os.getenv("AUTH_ISSUER_URL", "").rstrip("/")
    audience = os.getenv("AUTH_AUDIENCE", "")
    if provider != "auth0" or not issuer or not audience:
        raise HTTPException(status_code=503, detail="JWT authentication is not fully configured.")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required.", headers={"WWW-Authenticate": "Bearer"})
    token = authorization.removeprefix("Bearer ").strip()
    try:
        signing_key = _jwks_client(issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"{issuer}/",
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=401, detail="Invalid bearer token.", headers={"WWW-Authenticate": "Bearer"}) from error
    return claims


def require_role(role: str) -> Callable[..., dict[str, Any]]:
    def dependency(
        authorization: str | None = Header(default=None),
        session_token: str | None = Cookie(default=None, alias="prahari_access_token"),
    ) -> dict[str, Any]:
        credential = authorization or (f"Bearer {session_token}" if session_token else None)
        principal = _principal(credential)
        permissions = principal.get("permissions", [])
        roles = principal.get("https://prahari.dev/roles", [])
        if role not in permissions and role not in roles:
            raise HTTPException(status_code=403, detail=f"The {role} role is required.")
        return principal

    return dependency


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
