"""Polling detector process suitable for local Compose deployments."""

from __future__ import annotations

import argparse
import time

from detector.alert import detect
from prahari.store import audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://target_app:8000")
    parser.add_argument("--interval", type=int, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            alert = detect(args.url)
            if alert:
                audit("alert_fired", {"type": alert.type, "evidence": alert.evidence}, actor="detector")
        except Exception as error:
            audit("detector_error", {"error": str(error)}, actor="detector")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
