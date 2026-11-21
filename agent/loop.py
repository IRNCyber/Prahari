from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.tools import LocalTools
from target_app.state import read_state
from prahari.store import audit

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSES = {
    "bad_deploy": ("A recent deploy removed null handling for discount_code.", "discount", "target_app/app.py"),
    "config": ("The configured database pool is saturated under load.", "pool", "target_app/state.py"),
    "slow_query": ("Checkout is degraded by an inefficient product lookup.", "query", "target_app/app.py"),
    "dep_outage": ("The payment provider is returning 503 responses.", "provider", "target_app/app.py"),
}


def run() -> dict[str, Any]:
    tools, trace = LocalTools(), []

    def call(name: str, **kwargs: Any) -> dict[str, Any]:
        result = getattr(tools, name)(**kwargs)
        trace.append({"time": datetime.now(UTC).isoformat(), "tool": name, "result": result})
        return result

    scenario = read_state().get("scenario")
    metrics, logs, deploys = call("query_metrics", metric="service_health"), call("query_logs", service="checkout"), call("get_recent_deploys")
    if not scenario:
        result: dict[str, Any] = {"status": "no_incident", "summary": "No active failure scenario.", "trace": trace, "confidence": "high"}
    else:
        diagnosis, query, path = DIAGNOSES[str(scenario)]
        memory = call("search_past_incidents", query=query)
        call("search_code", pattern=query)
        evidence = [metrics["evidence_id"], logs["evidence_id"], deploys["evidence_id"], memory["evidence_id"]]
        if scenario == "dep_outage":
            result = {"status": "escalated", "diagnosis": diagnosis, "evidence": evidence, "confidence": "high", "escalation": call("escalate", reason=diagnosis, evidence=evidence), "trace": trace}
        else:
            patch = call("propose_patch", path=path, diff=f"# Proposed safe fix for {scenario}\n")
            result = {"status": "awaiting_fix_application", "diagnosis": diagnosis, "evidence": evidence, "confidence": "high", "patch": patch, "staging": call("deploy_staging", branch=patch["branch"]), "trace": trace}
    output = ROOT / "artifacts" / "incident_trace.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    audit("investigation_completed", {"status": result["status"], "scenario": scenario}, actor="agent")
    return result
