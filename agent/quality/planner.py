"""Evidence ranking, bounded retries, rollback-first decisions, and replay caching."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from prahari.atomic import atomic_write_text

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(os.getenv("PRAHARI_DATA_DIR", ROOT / "artifacts")) / "replay-cache"


def rank_hypotheses(
    metrics: dict[str, Any],
    logs: dict[str, Any],
    deployments: dict[str, Any],
) -> list[dict[str, Any]]:
    text = " ".join(str(item) for item in logs.get("clusters", [])).lower()
    values = metrics.get("values", {})
    candidates: list[tuple[str, float, str]] = []
    if "503" in text or "provider" in text:
        candidates.append(("external_dependency_failure", 0.95, str(logs.get("evidence_id", ""))))
    if "discount_code" in text or "null" in text:
        candidates.append(("checkout_regression", 0.9, str(logs.get("evidence_id", ""))))
    if values.get("p95_latency_ms", 0) > 1000:
        candidates.append(("latency_degradation", 0.85, str(metrics.get("evidence_id", ""))))
    if "db_connections" in values and values["db_connections"] <= 1:
        candidates.append(("database_pool_saturation", 0.8, str(metrics.get("evidence_id", ""))))
    if deployments.get("deploys"):
        candidates.append(("recent_deployment_regression", 0.55, str(deployments.get("evidence_id", ""))))
    return [
        {"hypothesis": name, "confidence": confidence, "evidence": [evidence] if evidence else []}
        for name, confidence, evidence in sorted(candidates, key=lambda item: item[1], reverse=True)
    ]


def citations_are_grounded(text: str, evidence_ids: set[str]) -> bool:
    citations = set(re.findall(r"\b(?:metric|log|deploy|memory|code(?:-search)?|alert|hypothesis)-[a-f0-9]{6,}\b", text))
    return citations.issubset(evidence_ids)


def retry_delay(attempt: int, transient: bool, idempotent: bool, max_attempts: int = 3) -> float | None:
    if not transient or not idempotent or attempt < 1 or attempt >= max_attempts:
        return None
    return min(0.25 * (2 ** (attempt - 1)), 2.0)


def rollback_first(recent_error_rate: float, baseline_error_rate: float, recent_p95_ms: float, baseline_p95_ms: float) -> bool:
    return recent_error_rate > max(0.05, baseline_error_rate * 2) or recent_p95_ms > max(1500, baseline_p95_ms * 2)


def replay_cache_key(recording: bytes, revision: str) -> str:
    return hashlib.sha256(revision.encode() + b"\0" + recording).hexdigest()


def cached_replay(key: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid replay cache key.")
    path = CACHE / f"{key}.json"
    if not path.is_file():
        return None
    cached = json.loads(path.read_text(encoding="utf-8"))
    if time.time() - float(cached["created_at"]) > 3600:
        path.unlink(missing_ok=True)
        return None
    return cached["result"]


def cache_replay(key: str, result: dict[str, Any]) -> None:
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("Invalid replay cache key.")
    atomic_write_text(CACHE / f"{key}.json", json.dumps({"created_at": time.time(), "result": result}))
