from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ALERT_PATH = ROOT / "artifacts" / "latest_alert.json"


@dataclass
class Alert:
    type: str
    service: str
    window_seconds: int
    evidence: list[str]
    created_at: str

    def save(self) -> None:
        ALERT_PATH.parent.mkdir(exist_ok=True)
        ALERT_PATH.write_text(__import__("json").dumps(asdict(self), indent=2), encoding="utf-8")


def detect(base_url: str = "http://localhost:8000") -> Alert | None:
    metrics = httpx.get(f"{base_url}/metrics", timeout=3).text
    errors = _metric(metrics, "checkout_errors_total")
    requests = _metric(metrics, "checkout_requests_total")
    error_rate = errors / requests if requests else 0
    if error_rate > 0.05:
        alert = Alert("high_error_rate", "checkout", 20,
                      [f"metric:error_rate={error_rate:.2%}", f"metric:errors={errors:.0f}"],
                      datetime.now(UTC).isoformat())
        alert.save()
        return alert
    return None


def _metric(text: str, name: str) -> float:
    return sum(float(line.rsplit(" ", 1)[1]) for line in text.splitlines()
               if line.startswith(name) and not line.startswith(f"{name}_created"))
