from __future__ import annotations

from agent.tools import LocalTools
from pathlib import Path

from prahari.store import audit


def create_pr(diagnosis: str, verification: dict[str, object]) -> dict[str, object]:
    body = "\n".join([
        "## Summary", diagnosis,
        "## Root cause", diagnosis,
        "## Evidence", "See `artifacts/incident_trace.json`.",
        "## Verification", str(verification),
        "## Risk", "Local sample-service demonstration only.",
        "## Rollback", "Clear the injected scenario with `python main.py heal`.",
    ])
    result = LocalTools().open_pr("Prahari: verified incident remediation", body)
    postmortem = Path(__file__).resolve().parents[1] / "artifacts" / "postmortem.md"
    postmortem.write_text("# Blameless postmortem\n\n## Summary\n" + diagnosis + "\n\n## Verification\n" + str(verification), encoding="utf-8")
    audit("postmortem_created", {"path": str(postmortem)}, actor="reporter")
    return result
