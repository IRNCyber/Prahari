from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.tools import LocalTools
from otel.tracing import traced
from prahari.atomic import atomic_write_text
from prahari.store import audit, record_tool_call
from target_app.state import read_state

ROOT = Path(__file__).resolve().parents[1]
@traced("agent.investigation")
def run(alert: dict[str, Any] | None = None) -> dict[str, Any]:
    scenario = read_state().get("scenario")
    if __import__("os").getenv("ANTHROPIC_API_KEY", "").strip():
        from agent.llm import investigate

        result = investigate(str(scenario) if scenario else None, alert)
        result["trace_path"] = _write_result(result)
        audit("investigation_completed", {"status": result["status"], "scenario": scenario}, actor="agent")
        return result
    result = _run_without_model(scenario, alert)
    result["trace_path"] = _write_result(result)
    audit("investigation_completed", {"status": result["status"], "scenario": scenario}, actor="agent")
    return result


def _write_result(result: dict[str, Any]) -> str:
    output = ROOT / "artifacts" / "incident_trace.json"
    atomic_write_text(output, json.dumps(result, indent=2))
    return str(output)


def _run_without_model(scenario: object, alert: dict[str, Any] | None = None) -> dict[str, Any]:
    tools, trace = LocalTools(), []

    def call(name: str, **kwargs: Any) -> dict[str, Any]:
        try:
            result = getattr(tools, name)(**kwargs)
        except Exception as error:
            record_tool_call(name, kwargs, {"error": type(error).__name__}, status="failed")
            raise
        record_tool_call(name, kwargs, result)
        trace.append({"time": datetime.now(UTC).isoformat(), "tool": name, "result": result})
        return result

    metrics, logs, deploys = call("query_metrics", metric="service_health"), call("query_logs", service="checkout"), call("get_recent_deploys")
    if not scenario and not alert:
        result: dict[str, Any] = {"status": "no_incident", "summary": "No active failure scenario.", "trace": trace, "confidence": "high"}
    else:
        observed_logs = str(logs.get("clusters", []))
        if alert:
            observed_logs = f"{alert.get('type', 'alert')}: {alert.get('evidence', [])}; {observed_logs}"
        diagnosis = observed_logs
        query = next((token for token in ("discount", "pool", "query", "provider") if token in observed_logs.lower()), "checkout")
        memory = call("search_past_incidents", query=query)
        call("search_code", pattern=query)
        evidence = [metrics["evidence_id"], logs["evidence_id"], deploys["evidence_id"], memory["evidence_id"]]
        if "provider" in observed_logs.lower() or "503" in observed_logs:
            result = {"status": "escalated", "diagnosis": diagnosis, "evidence": evidence, "confidence": "high", "escalation": call("escalate", reason=diagnosis, evidence=evidence), "trace": trace}
        else:
            result = {
                "status": "needs_llm",
                "diagnosis": diagnosis,
                "evidence": evidence,
                "confidence": "low",
                "summary": "No model key configured; gathered evidence only and made no patch.",
                "trace": trace,
            }
    return result
