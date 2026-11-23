from fastapi.testclient import TestClient

import agent.loop as agent_loop
from agent.loop import run
from dashboard.app import app
from faults.scenarios import heal, inject
from prahari.policy import allow_approval, allow_patch
from prahari.store import recent_audit


def teardown_function() -> None:
    heal()


def test_patch_policy_rejects_unapproved_paths() -> None:
    assert not allow_patch("prahari/store.py", "high").allowed
    assert allow_patch("target_app/app.py", "high").allowed


def test_approval_policy_requires_named_human_and_checks() -> None:
    assert not allow_approval(True, "").allowed
    assert not allow_approval(False, "reviewer").allowed
    assert allow_approval(True, "reviewer").allowed


def test_dependency_outage_escalates_without_patch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(agent_loop, "ROOT", tmp_path)
    inject("dep_outage")
    result = run()
    assert result["status"] == "escalated"
    assert "patch" not in result


def test_dashboard_persists_audit_and_gates_approval() -> None:
    client = TestClient(app)
    client.post("/api/control/bad_deploy")
    client.post("/api/control/heal")
    assert client.get("/api/state").json()["scenario"] is None
    assert recent_audit()
