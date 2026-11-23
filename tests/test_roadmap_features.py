from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import detector.service as detector_service
from agent.quality.planner import citations_are_grounded, retry_delay, rollback_first
from agent.tools.local import LocalTools
from dashboard.app import app
from detector.alert import Alert, detect
from prahari.store import (
    _redact,
    create_signed_approval,
    recent_alerts,
    record_alert,
    resolve_alert,
)
from risk.engine import assess
from seed import demo as demo_seed
from seed.demo import seed_demo_data
from slo.service import evaluate_slo


def test_alerts_are_deduplicated_and_resolvable() -> None:
    fingerprint = "test:deduplication"
    first, should_investigate = record_alert(fingerprint, "high", "test alert", ["metric-abcdef12"])
    second, should_investigate_again = record_alert(fingerprint, "high", "updated alert", ["metric-abcdef12"])

    assert should_investigate
    assert not should_investigate_again
    assert first["id"] == second["id"]
    assert resolve_alert(fingerprint)
    assert not resolve_alert(fingerprint)


def test_incident_remains_active_until_its_last_alert_is_resolved() -> None:
    first, _ = record_alert("test:shared-a", "high", "first", [])
    second, _ = record_alert("test:shared-b", "high", "second", [])
    assert first["incident_id"] == second["incident_id"]

    assert resolve_alert("test:shared-a")
    assert next(item for item in recent_alerts() if item["fingerprint"] == "test:shared-b")["status"] == "firing"
    assert resolve_alert("test:shared-b")


def test_audit_redaction_removes_credentials() -> None:
    redacted = _redact({
        "SENTRY_DSN": "https://private@example.invalid/123",
        "message": "contact alice@example.com with Bearer abc.def.ghi",
    })

    assert redacted["SENTRY_DSN"] == "[REDACTED]"
    assert "alice@example.com" not in redacted["message"]
    assert "abc.def.ghi" not in redacted["message"]


def test_approval_is_signed_with_configured_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRAHARI_APPROVER_TOKEN", "test-approval-secret")
    approval = create_signed_approval("reviewer", "Regression test and replay passed")
    expected = hmac.new(
        b"test-approval-secret",
        f"{approval['id']}\nreviewer\nRegression test and replay passed\n{approval['expires_at']}".encode(),
        hashlib.sha256,
    ).hexdigest()

    assert hmac.compare_digest(approval["signature"], expected)


def test_risk_policy_rejects_empty_and_protected_diffs() -> None:
    assert not assess("no file headers")["allowed"]
    protected = "diff --git a/prahari/auth.py b/prahari/auth.py\n"
    assert not assess(protected)["allowed"]
    app_change = "diff --git a/target_app/app.py b/target_app/app.py\n"
    assert assess(app_change)["missing_regression_test"]


def test_quality_helpers_require_grounded_citations_and_safe_retries() -> None:
    assert citations_are_grounded("log-abcdef12", {"log-abcdef12"})
    assert not citations_are_grounded("log-deadbeef", {"log-abcdef12"})
    assert retry_delay(1, transient=True, idempotent=True) == 0.25
    assert retry_delay(1, transient=False, idempotent=True) is None
    assert rollback_first(0.2, 0.01, 100, 50)


def test_local_tools_refuse_secrets_and_return_safe_source() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        LocalTools().read_file(".env")
    assert "def health" in LocalTools().read_file("target_app/app.py")["content"]


def test_github_webhook_requires_valid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/prahari-checkout")
    payload = {
        "repository": {"full_name": "example/prahari-checkout"},
        "deployment": {"sha": "abc123", "environment": "staging"},
        "deployment_status": {"state": "success"},
    }
    body = json.dumps(payload).encode()
    signature = hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()
    client = TestClient(app)

    response = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "deployment_status", "X-Hub-Signature-256": f"sha256={signature}"},
    )
    assert response.status_code == 200
    assert response.json()["accepted"]
    resolve_alert("github-deployment:example/prahari-checkout:abc123:success")
    rejected = client.post(
        "/api/webhooks/github",
        content=body,
        headers={"X-GitHub-Event": "deployment_status", "X-Hub-Signature-256": "sha256=invalid"},
    )
    assert rejected.status_code == 401


def test_gitlab_webhook_uses_shared_secret_and_repository_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "test-gitlab-secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/prahari-checkout")
    response = TestClient(app).post(
        "/api/webhooks/gitlab",
        headers={"X-Gitlab-Event": "Deployment Hook", "X-Gitlab-Token": "test-gitlab-secret"},
        json={
            "project": {"path_with_namespace": "example/prahari-checkout"},
            "sha": "gitlab123",
            "environment": "staging",
            "status": "success",
        },
    )

    assert response.status_code == 200
    assert response.json()["accepted"]
    assert not response.json()["triggered"]


def test_slo_window_aggregates_error_and_latency_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    exposition = """checkout_requests_total{route="/checkout",status="200"} 20
checkout_requests_total{route="/checkout",status="500"} 3
prahari_window_requests 10
prahari_window_errors 2
prahari_window_p95_latency_ms 725"""
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            text=exposition,
            request=httpx.Request("GET", "http://metrics"),
        ),
    )

    result = evaluate_slo()
    assert result["request_count"] == 10
    assert result["error_count"] == 2
    assert result["error_rate"] == pytest.approx(0.2)
    assert result["p95_latency_ms"] == 725
    resolve_alert("slo:error_rate")


def test_detector_uses_window_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    response_text = "prahari_window_requests 10\nprahari_window_errors 2\n"
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            text=response_text,
            request=httpx.Request("GET", "http://metrics"),
        ),
    )
    monkeypatch.setattr(Alert, "save", lambda self: None)

    alert = detect()
    assert alert is not None
    assert alert.type == "high_error_rate"
    assert alert.window_seconds == 300


def test_detector_worker_retries_transient_errors_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    delays: list[float] = []

    async def poll_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts > 3:
            raise asyncio.CancelledError
        raise RuntimeError("temporary poll failure")

    async def sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(detector_service, "POLL_INTERVAL", 3)
    monkeypatch.setattr(detector_service, "poll_once", poll_once)
    monkeypatch.setattr(detector_service.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(detector_service._poll_forever())

    assert attempts == 4
    assert delays == [3, 6, 12]


def test_demo_seed_is_repeatable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    recording = tmp_path / "captured-traffic.json"
    monkeypatch.setattr(demo_seed, "DEFAULT_RECORDING", recording)

    first = seed_demo_data()
    second = seed_demo_data()

    assert first["alerts_seeded"] == second["alerts_seeded"] == 2
    assert first["deployments_seeded"] == second["deployments_seeded"] == 3
    assert recording.is_file()
    assert len(json.loads(recording.read_text(encoding="utf-8"))) >= 1


def test_authentication_is_required_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRAHARI_ENV", "production")
    monkeypatch.setenv("AUTH_PROVIDER", "none")
    response = TestClient(app).get("/api/state")
    assert response.status_code == 503
