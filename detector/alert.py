from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from prahari.atomic import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
ALERT_PATH = ROOT / "artifacts" / "latest_alert.json"
CONFIG = yaml.safe_load((ROOT / "detector" / "config.yaml").read_text(encoding="utf-8"))


@dataclass
class Alert:
    type: str
    service: str
    window_seconds: int
    evidence: list[str]
    created_at: str

    def save(self) -> None:
        atomic_write_text(ALERT_PATH, json.dumps(asdict(self), indent=2))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def detect(base_url: str = "http://localhost:8000") -> Alert | None:
    metrics_response = httpx.get(f"{base_url}/metrics", timeout=3)
    metrics_response.raise_for_status()
    metrics = metrics_response.text
    has_window_metrics = any(line.startswith("prahari_window_requests ") for line in metrics.splitlines())
    if has_window_metrics:
        requests = _metric(metrics, "prahari_window_requests")
        errors = _metric(metrics, "prahari_window_errors")
    else:
        errors = _metric(metrics, "checkout_errors_total")
        requests = _metric(metrics, "checkout_requests_total")
    error_rate = errors / requests if requests else 0
    if error_rate > float(CONFIG["error_rate_threshold"]):
        alert = Alert("high_error_rate", "checkout", int(CONFIG["window_seconds"]),
                      [f"metric:error_rate={error_rate:.2%}", f"metric:errors={errors:.0f}"],
                      datetime.now(UTC).isoformat())
        alert.save()
        return alert
    return None


def _metric(text: str, name: str) -> float:
    return sum(float(line.rsplit(" ", 1)[1]) for line in text.splitlines()
               if line.startswith(name) and not line.startswith(f"{name}_created"))
