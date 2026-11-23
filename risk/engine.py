"""Conservative blast-radius scoring for local remediation proposals."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "risk" / "policy.json").read_text(encoding="utf-8"))


def assess(diff: str) -> dict[str, Any]:
    files = sorted(set(re.findall(r"^diff --git a/(.+?) b/(.+)$", diff, flags=re.MULTILINE)))
    changed = [new for _, new in files]
    blocked = [path for path in changed if any(path.startswith(prefix) for prefix in POLICY["blocked_paths"])]
    changes_sample_code = any(path.startswith(("target_app/", "faults/")) for path in changed)
    has_regression_test = any(path.startswith("tests/test_") for path in changed)
    missing_regression_test = changes_sample_code and not has_regression_test
    score = 10 + max(0, len(changed) - 1) * 20
    if not changed:
        score = 100
    score += sum(20 for path in changed if not path.startswith(("target_app/", "faults/", "tests/")))
    score += sum(20 for line in diff.splitlines() if line.startswith("+") and any(word in line.lower() for word in ("subprocess", "eval(", "exec(", "pickle", "shell=true")))
    score = min(score, 100)
    if blocked:
        score = 100
    rollback = "Revert the generated Prahari commit; no deployment is performed by patch generation."
    return {
        "score": score,
        "risk": "low" if score < 30 else "medium" if score < 60 else "high",
        "changed_files": changed,
        "blocked_files": blocked,
        "requires_regression_test": changes_sample_code,
        "has_regression_test": has_regression_test,
        "missing_regression_test": missing_regression_test,
        "rollback_plan": rollback,
        "allowed": (
            bool(changed)
            and not blocked
            and not missing_regression_test
            and len(changed) <= int(POLICY["max_changed_files"])
            and score < 60
        ),
    }
