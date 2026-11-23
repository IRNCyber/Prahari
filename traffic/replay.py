from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from agent.quality.planner import cache_replay, cached_replay, replay_cache_key
from prahari.atomic import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDING = ROOT / "artifacts" / "checkout_replay.json"
DEFAULT_REQUESTS = [
    {"method": "POST", "path": "/checkout", "json": {"items": [{"price": 299, "quantity": 1}]}},
    {"method": "POST", "path": "/checkout", "json": {"items": [{"price": 99, "quantity": 2}]}},
]


def record(path: Path = DEFAULT_RECORDING) -> Path:
    path.parent.mkdir(exist_ok=True)
    atomic_write_text(path, json.dumps(DEFAULT_REQUESTS, indent=2))
    return path


def replay(base_url: str, path: Path = DEFAULT_RECORDING, revision: str | None = None) -> dict[str, object]:
    if not path.exists():
        record(path)
    recording = path.read_bytes()
    cache_key = replay_cache_key(recording, f"{revision}:{base_url}") if revision else None
    cached = cached_replay(cache_key) if cache_key else None
    if cached is not None:
        return {**cached, "cache_hit": True}
    requests = json.loads(recording)
    started = time.perf_counter()
    failures = 0
    statuses: list[int] = []
    latencies: list[float] = []
    with httpx.Client(base_url=base_url, timeout=5) as client:
        for item in requests:
            request_started = time.perf_counter()
            response = client.request(item["method"], item["path"], json=item.get("json"))
            latencies.append((time.perf_counter() - request_started) * 1000)
            statuses.append(response.status_code)
            failures += response.status_code >= 500
    ordered_latencies = sorted(latencies)
    p95_index = max(0, min(len(ordered_latencies) - 1, int(0.95 * len(ordered_latencies) + 0.999) - 1))
    result: dict[str, object] = {
        "requests": len(requests),
        "failures": failures,
        "error_rate": failures / max(len(requests), 1),
        "statuses": statuses,
        "p95_latency_ms": round(ordered_latencies[p95_index], 2) if ordered_latencies else 0,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    if cache_key:
        cache_replay(cache_key, result)
    return {**result, "cache_hit": False}
