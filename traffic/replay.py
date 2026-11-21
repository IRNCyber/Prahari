from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDING = ROOT / "artifacts" / "checkout_replay.json"
DEFAULT_REQUESTS = [
    {"method": "POST", "path": "/checkout", "json": {"items": [{"price": 299, "quantity": 1}]}},
    {"method": "POST", "path": "/checkout", "json": {"items": [{"price": 99, "quantity": 2}]}},
]


def record(path: Path = DEFAULT_RECORDING) -> Path:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(DEFAULT_REQUESTS, indent=2), encoding="utf-8")
    return path


def replay(base_url: str, path: Path = DEFAULT_RECORDING) -> dict[str, object]:
    if not path.exists():
        record(path)
    requests = json.loads(path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    failures = 0
    statuses: list[int] = []
    with httpx.Client(base_url=base_url, timeout=5) as client:
        for item in requests:
            response = client.request(item["method"], item["path"], json=item.get("json"))
            statuses.append(response.status_code)
            failures += response.status_code >= 500
    return {
        "requests": len(requests),
        "failures": failures,
        "error_rate": failures / max(len(requests), 1),
        "statuses": statuses,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
