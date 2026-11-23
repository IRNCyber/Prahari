"""Error-rate and latency SLO evaluation from Prometheus exposition data."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import yaml

from prahari.store import record_alert, resolve_alert

ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "slo" / "config.yaml").read_text(encoding="utf-8"))
_SAMPLE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([0-9.eE+-]+)$")


def _samples(exposition: str, metric_name: str) -> list[tuple[dict[str, str], float]]:
    samples = []
    for line in exposition.splitlines():
        match = _SAMPLE.match(line.strip())
        if not match or match.group(1) != metric_name:
            continue
        labels = dict(re.findall(r'(\w+)="([^"]*)"', match.group(2) or ""))
        samples.append((labels, float(match.group(3))))
    return samples


def evaluate_slo(metrics_url: str = "http://localhost:8000/metrics") -> dict[str, Any]:
    response = httpx.get(metrics_url, timeout=5)
    response.raise_for_status()
    exposition = response.text
    requests = sum(value for _, value in _samples(exposition, "checkout_requests_total"))
    errors = sum(
        value
        for labels, value in _samples(exposition, "checkout_requests_total")
        if labels.get("status", "").startswith(("4", "5"))
    )
    error_rate = errors / requests if requests else 0.0
    window_requests = _samples(exposition, "prahari_window_requests")
    window_errors = _samples(exposition, "prahari_window_errors")
    p95_ms: float | None
    if window_requests:
        requests = sum(value for _, value in window_requests)
        errors = sum(value for _, value in window_errors)
        p95_samples = _samples(exposition, "prahari_window_p95_latency_ms")
        p95_ms = round(max((value for _, value in p95_samples), default=0.0), 2)
    else:
        histogram = _samples(exposition, "checkout_request_latency_seconds_bucket")
        bucket_counts: dict[str, float] = defaultdict(float)
        for labels, value in histogram:
            bucket_counts[labels.get("le", "+Inf")] += value
        total = bucket_counts.get("+Inf", 0.0)
        finite_buckets = sorted(
            (float(bound), count)
            for bound, count in bucket_counts.items()
            if bound != "+Inf"
        )
        bucket = next((bound for bound, count in finite_buckets if total and count >= total * 0.95), float("inf"))
        p95_ms = round(bucket * 1000, 2) if bucket != float("inf") else None
    error_rate = errors / requests if requests else 0.0
    violations = []
    if error_rate > float(CONFIG["error_rate"]["alert_threshold"]):
        violations.append({"slo": "error_rate", "observed": error_rate, "threshold": CONFIG["error_rate"]["alert_threshold"]})
    latency_limit = float(CONFIG["latency"]["alert_threshold_ms"])
    if p95_ms is not None and p95_ms > latency_limit:
        violations.append({"slo": "p95_latency_ms", "observed": p95_ms, "threshold": latency_limit})
    for violation in violations:
        record_alert(
            fingerprint=f"slo:{violation['slo']}",
            severity="high",
            summary=f"SLO violation: {violation['slo']}",
            evidence=[str(violation)],
            suppression_seconds=int(CONFIG["alerting"]["suppression_seconds"]),
        )
    active_slos = {str(violation["slo"]) for violation in violations}
    for metric_name in ("error_rate", "p95_latency_ms"):
        if metric_name not in active_slos:
            resolve_alert(f"slo:{metric_name}")
    return {
        "window_seconds": max(1, int(os.getenv("PRAHARI_SLO_WINDOW_SECONDS", CONFIG["window_seconds"]))),
        "latency_target_ms": float(CONFIG["latency"]["p95_target_ms"]),
        "request_count": int(requests),
        "error_count": int(errors),
        "error_rate": error_rate,
        "error_budget_remaining": max(0.0, 1 - error_rate / max(1e-9, 1 - float(CONFIG["error_rate"]["objective"]))),
        "p95_latency_ms": p95_ms,
        "violations": violations,
        "healthy": not violations,
    }
