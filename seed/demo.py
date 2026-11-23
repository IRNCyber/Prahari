"""Load deterministic incident history and captured checkout traffic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prahari.store import (
    audit,
    recent_deployments,
    record_alert,
    record_deployment,
    resolve_alert,
)
from traffic.replay import DEFAULT_RECORDING, record

ROOT = Path(__file__).resolve().parents[1]


def seed_demo_data() -> dict[str, Any]:
    data = json.loads((ROOT / "seed" / "demo_data.json").read_text(encoding="utf-8"))
    known_revisions = {item["revision"] for item in recent_deployments(limit=1000)}
    for deployment in data["deployments"]:
        revision = deployment["revision"]
        if revision not in known_revisions:
            record_deployment(
                "demo",
                "example/prahari-checkout",
                revision,
                deployment["environment"],
                deployment["state"],
            )
            audit("demo_deployment_seeded", {"revision": revision}, actor="seed")
    for alert in data["alerts"]:
        fingerprint = f"seed:{alert['fingerprint']}"
        record_alert(
            fingerprint,
            alert["severity"],
            alert["summary"],
            alert["evidence"],
            suppression_seconds=0,
        )
        resolve_alert(fingerprint)
    recording = record(DEFAULT_RECORDING)
    return {
        "deployments_seeded": len(data["deployments"]),
        "alerts_seeded": len(data["alerts"]),
        "traffic_recording": str(recording),
    }
