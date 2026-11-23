"""Non-bypassable local safety policy for remediation actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def allow_patch(path: str, confidence: str, production: bool = False) -> PolicyDecision:
    if production:
        return PolicyDecision(False, "Production writes require external human approval integration.")
    if confidence not in {"medium", "high"}:
        return PolicyDecision(False, "Low-confidence diagnoses may only escalate or recommend rollback.")
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = normalized.parts
    if ".." in parts:
        return PolicyDecision(False, "Patch paths may not traverse outside the project.")
    if parts and parts[0] == "Prahari":
        normalized = PurePosixPath(*parts[1:])
    if not normalized.as_posix().startswith(("target_app/", "faults/", "tests/test_")):
        return PolicyDecision(False, "Patch target is outside the approved sample-service scope.")
    return PolicyDecision(True, "Branch-only local patch is permitted.")


def allow_approval(verification_passed: bool, human: str) -> PolicyDecision:
    if not verification_passed:
        return PolicyDecision(False, "All verification gates must be green.")
    if not human.strip():
        return PolicyDecision(False, "A named human approver is required.")
    return PolicyDecision(True, "Verified local PR artifact may be approved.")
