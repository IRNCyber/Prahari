from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from target_app.state import read_state
from prahari.policy import allow_patch
from prahari.store import audit

ROOT = Path(__file__).resolve().parents[2]


class LocalTools:
    """Local-only implementations of Prahari's safety-guarded tool contracts."""

    def _scenario(self) -> str | None:
        return read_state().get("scenario")  # type: ignore[return-value]

    def query_logs(self, service: str, level: str = "error", since: str = "20m", grep: str = "") -> dict[str, Any]:
        messages = {"bad_deploy": "ValueError: discount_code cannot be null on POST /checkout", "config": "database-pool wait threshold exceeded", "slow_query": "product lookup exceeds 1500ms", "dep_outage": "payment provider returned HTTP 503"}
        return {"evidence_id": "log-1", "service": service, "clusters": [messages.get(self._scenario(), "no active error cluster")]}

    def query_metrics(self, metric: str, window: str = "20s") -> dict[str, Any]:
        values = {"bad_deploy": {"error_rate": .5, "p95_latency_ms": 40, "db_connections": 3}, "config": {"error_rate": 0, "p95_latency_ms": 1700, "db_connections": 1}, "slow_query": {"error_rate": 0, "p95_latency_ms": 1700, "db_connections": 3}, "dep_outage": {"error_rate": 1, "p95_latency_ms": 25, "db_connections": 3}}
        return {"evidence_id": "metric-1", "window": window, "values": values.get(self._scenario(), {"error_rate": 0, "p95_latency_ms": 20, "db_connections": 3})}

    def get_recent_deploys(self, count: int = 5) -> dict[str, Any]:
        return {"evidence_id": "deploy-1", "deploys": [{"sha": "demo-bad-deploy", "summary": "checkout: streamline discount handling"}][:count]}

    def read_file(self, path: str) -> dict[str, Any]:
        candidate = (ROOT / path).resolve()
        if ROOT not in candidate.parents:
            raise ValueError("Path must remain inside the project")
        return {"evidence_id": "code-1", "path": path, "content": candidate.read_text(encoding="utf-8")[:5000]}

    def search_code(self, pattern: str) -> dict[str, Any]:
        matches = [f"{path.relative_to(ROOT)}:{number}: {line.strip()}" for path in ROOT.rglob("*.py") if ".venv" not in path.parts for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if pattern.lower() in line.lower()]
        return {"evidence_id": "code-search-1", "pattern": pattern, "matches": matches[:20]}

    def search_past_incidents(self, query: str) -> dict[str, Any]:
        matches = [path.name for path in (ROOT / "incidents").glob("*.md") if query.lower() in path.read_text(encoding="utf-8").lower()]
        return {"evidence_id": "memory-1", "matches": matches}

    def propose_patch(self, path: str, diff: str) -> dict[str, Any]:
        decision = allow_patch(path, confidence="high")
        if not decision.allowed:
            return {"evidence_id": "patch-1", "applied": False, "reason": decision.reason}
        output = ROOT / "artifacts" / "proposed_fix.diff"
        output.parent.mkdir(exist_ok=True)
        output.write_text(diff, encoding="utf-8")
        result = {"evidence_id": "patch-1", "branch": "prahari/incident-fix", "path": path, "diff_path": str(output), "guardrail": "Proposal saved only; main was not modified."}
        audit("patch_proposed", result, actor="agent")
        return result

    def run_tests(self) -> dict[str, Any]:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        output = {"evidence_id": "test-1", "passed": result.returncode == 0, "output": (result.stdout + result.stderr)[-2000:]}
        audit("tests_completed", {"passed": output["passed"]}, actor="verifier")
        return output

    def deploy_staging(self, branch: str) -> dict[str, Any]:
        return {"evidence_id": "staging-1", "branch": branch, "environment": "local-staging", "deployed": True}

    def replay_traffic(self, window: str = "recorded") -> dict[str, Any]:
        return {"evidence_id": "replay-1", "window": window, "result": "ready for local service replay"}

    def open_pr(self, title: str, body: str) -> dict[str, Any]:
        output = ROOT / "artifacts" / "PR.md"
        output.parent.mkdir(exist_ok=True)
        output.write_text(f"# {title}\n\n{body}", encoding="utf-8")
        result = {"evidence_id": "pr-1", "path": str(output), "status": "awaiting human approval"}
        audit("pr_opened", result, actor="reporter")
        return result

    def escalate(self, reason: str, evidence: list[str]) -> dict[str, Any]:
        result = {"evidence_id": "escalation-1", "status": "escalated", "reason": reason, "evidence": evidence}
        audit("incident_escalated", result, actor="agent")
        return result
