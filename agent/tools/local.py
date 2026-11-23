from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from agent.quality.planner import rank_hypotheses, rollback_first
from prahari.atomic import atomic_write_text
from prahari.policy import allow_patch
from prahari.store import _redact, audit, recent_deployments
from risk.engine import assess
from target_app.state import read_state

ROOT = Path(__file__).resolve().parents[2]


def _evidence_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


class LocalTools:
    """Local-only implementations of Prahari's safety-guarded tool contracts."""

    def _scenario(self) -> str | None:
        return read_state().get("scenario")  # type: ignore[return-value]

    def query_logs(self, service: str, level: str = "error", since: str = "20m", grep: str = "") -> dict[str, Any]:
        target_url = __import__("os").getenv("TARGET_BASE_URL", "").rstrip("/")
        if target_url:
            response = httpx.get(f"{target_url}/debug/logs", params={"limit": 100}, timeout=5)
            response.raise_for_status()
            return {"evidence_id": _evidence_id("log"), "service": service, "clusters": response.json()}
        messages = {"bad_deploy": "ValueError: discount_code cannot be null on POST /checkout", "config": "database-pool wait threshold exceeded", "slow_query": "product lookup exceeds 1500ms", "dep_outage": "payment provider returned HTTP 503"}
        return {"evidence_id": _evidence_id("log"), "service": service, "clusters": [messages.get(self._scenario() or "", "no active error cluster")]}

    def query_metrics(self, metric: str, window: str = "20s") -> dict[str, Any]:
        target_url = __import__("os").getenv("TARGET_BASE_URL", "").rstrip("/")
        if target_url:
            response = httpx.get(f"{target_url}/metrics", timeout=5)
            response.raise_for_status()
            samples: dict[str, list[tuple[dict[str, str], float]]] = {}
            for line in response.text.splitlines():
                match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([0-9.eE+-]+)$', line.strip())
                if match:
                    labels = dict(re.findall(r'(\w+)="([^"]*)"', match.group(2) or ""))
                    samples.setdefault(match.group(1), []).append((labels, float(match.group(3))))
            requests = samples.get("checkout_requests_total", [])
            request_count = sum(value for _, value in requests)
            errors = sum(value for labels, value in requests if labels.get("status", "").startswith(("4", "5")))
            window_requests = samples.get("prahari_window_requests", [])
            window_errors = samples.get("prahari_window_errors", [])
            if window_requests:
                request_count = sum(value for _, value in window_requests)
                errors = sum(value for _, value in window_errors)
            buckets = samples.get("checkout_request_latency_seconds_bucket", [])
            window_latency = samples.get("prahari_window_p95_latency_ms", [])
            if window_latency:
                p95 = max(value for _, value in window_latency) / 1000
            else:
                bucket_counts: dict[str, float] = {}
                for labels, value in buckets:
                    boundary = labels.get("le", "+Inf")
                    bucket_counts[boundary] = bucket_counts.get(boundary, 0.0) + value
                total = bucket_counts.get("+Inf", 0.0)
                p95 = min(
                    (float(boundary) for boundary, value in bucket_counts.items() if boundary != "+Inf" and total and value >= total * 0.95),
                    default=0.0,
                )
            gauge = max((value for _, value in samples.get("checkout_db_connections", [])), default=0.0)
            return {
                "evidence_id": _evidence_id("metric"),
                "window": window,
                "values": {
                    "request_count": request_count,
                    "error_rate": errors / request_count if request_count else 0.0,
                    "p95_latency_ms": p95 * 1000,
                    "db_connections": gauge,
                },
            }
        values = {"bad_deploy": {"error_rate": .5, "p95_latency_ms": 40, "db_connections": 3}, "config": {"error_rate": 0, "p95_latency_ms": 1700, "db_connections": 1}, "slow_query": {"error_rate": 0, "p95_latency_ms": 1700, "db_connections": 3}, "dep_outage": {"error_rate": 1, "p95_latency_ms": 25, "db_connections": 3}}
        return {"evidence_id": _evidence_id("metric"), "window": window, "values": values.get(self._scenario() or "", {"error_rate": 0, "p95_latency_ms": 20, "db_connections": 3})}

    def get_recent_deploys(self, count: int = 5) -> dict[str, Any]:
        return {"evidence_id": _evidence_id("deploy"), "deploys": recent_deployments(count)}

    def read_file(self, path: str) -> dict[str, Any]:
        candidate = (ROOT / path).resolve()
        if ROOT not in candidate.parents:
            raise ValueError("Path must remain inside the project")
        parts = {part.lower() for part in candidate.relative_to(ROOT).parts}
        if (
            candidate.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".toml"}
            or any(part in {".git", ".venv", "artifacts", "data"} for part in parts)
            or any(term in candidate.name.lower() for term in (".env", "secret", "credential", "token"))
        ):
            raise ValueError("The requested file is outside the safe project-source allowlist.")
        content = candidate.read_text(encoding="utf-8")[:5000]
        return {"evidence_id": _evidence_id("code"), "path": path, "content": _redact(content)}

    def search_code(self, pattern: str) -> dict[str, Any]:
        if not pattern or len(pattern) > 200:
            raise ValueError("Search patterns must contain between 1 and 200 characters.")
        excluded = {".git", ".venv", "__pycache__", "artifacts", "data"}
        matches = [
            f"{path.relative_to(ROOT)}:{number}: {_redact(line.strip())}"
            for path in ROOT.rglob("*.py")
            if not excluded.intersection(path.parts)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if pattern.lower() in line.lower()
        ][:20]
        return {"evidence_id": _evidence_id("code-search"), "pattern": pattern, "matches": matches}

    def search_past_incidents(self, query: str) -> dict[str, Any]:
        terms = {term for term in query.lower().split() if len(term) > 2}
        ranked = []
        for path in (ROOT / "incidents").glob("*.md"):
            content = path.read_text(encoding="utf-8")
            words = {word.lower() for word in re.findall(r"[a-zA-Z0-9_]+", content)}
            overlap = len(terms & words) / max(1, len(terms | words))
            if overlap:
                ranked.append((overlap, path.name))
        matches = [name for _, name in sorted(ranked, reverse=True)[:10]]
        return {"evidence_id": _evidence_id("memory"), "matches": matches}

    def rank_hypotheses(self, metrics: dict[str, Any], logs: dict[str, Any], deployments: dict[str, Any]) -> dict[str, Any]:
        values = metrics.get("values", {})
        return {
            "evidence_id": _evidence_id("hypothesis"),
            "hypotheses": rank_hypotheses(metrics, logs, deployments),
            "rollback_first": rollback_first(
                float(values.get("error_rate", 0)),
                float(values.get("baseline_error_rate", 0)),
                float(values.get("p95_latency_ms", 0)),
                float(values.get("baseline_p95_ms", 0)),
            ),
        }

    def propose_patch(self, path: str, diff: str) -> dict[str, Any]:
        decision = allow_patch(path, confidence="high")
        if not decision.allowed:
            return {"evidence_id": _evidence_id("patch"), "applied": False, "reason": decision.reason}
        risk = assess(diff)
        if not risk["allowed"] or path not in [item.removeprefix("Prahari/") for item in risk["changed_files"]]:
            return {"evidence_id": _evidence_id("patch"), "applied": False, "reason": "Risk policy rejected the patch.", "risk": risk}
        from agent.patcher import create_patch_branch
        from agent.verifier import verify_worktree

        patch = create_patch_branch(diff, f"Prahari: remediate {path}")
        verification = verify_worktree(str(patch["worktree"]))
        output = ROOT / "artifacts" / "proposed_fix.diff"
        atomic_write_text(output, diff)
        result = {"evidence_id": _evidence_id("patch"), **patch, "path": path, "diff_path": str(output), "risk": risk, "verification": verification}
        audit("patch_proposed", result, actor="agent")
        return result

    def run_tests(self) -> dict[str, Any]:
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], check=False, cwd=ROOT, capture_output=True, text=True, timeout=120)
        output = {"evidence_id": _evidence_id("test"), "passed": result.returncode == 0, "output": (result.stdout + result.stderr)[-2000:]}
        audit("tests_completed", {"passed": output["passed"]}, actor="verifier")
        return output

    def run_tests_for(self, selector: str) -> dict[str, Any]:
        if not selector.startswith("tests/test_") or "::" not in selector:
            raise ValueError("Only a specific test selector under tests/ is allowed.")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", selector],
            check=False,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = {"evidence_id": _evidence_id("test"), "passed": result.returncode == 0, "output": (result.stdout + result.stderr)[-2000:]}
        audit("regression_test_completed", {"selector": selector, "passed": output["passed"]}, actor="verifier")
        return output

    def deploy_staging(self, branch: str) -> dict[str, Any]:
        return {"evidence_id": _evidence_id("staging"), "branch": branch, "environment": "local-staging", "deployed": False, "reason": "External deployment is not performed by the local demo."}

    def replay_traffic(self, window: str = "recorded") -> dict[str, Any]:
        return {"evidence_id": _evidence_id("replay"), "window": window, "result": "ready for local service replay"}

    def open_pr(self, title: str, body: str) -> dict[str, Any]:
        output = ROOT / "artifacts" / "PR.md"
        output.parent.mkdir(exist_ok=True)
        atomic_write_text(output, f"# {title}\n\n{body}")
        result: dict[str, object] = {"evidence_id": _evidence_id("pr"), "path": str(output), "status": "awaiting human approval"}
        audit("pr_opened", result, actor="reporter")
        return result

    def escalate(self, reason: str, evidence: list[str]) -> dict[str, Any]:
        result: dict[str, object] = {"evidence_id": _evidence_id("escalation"), "status": "escalated", "reason": reason, "evidence": evidence}
        audit("incident_escalated", result, actor="agent")
        return result
