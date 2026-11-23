"""Demonstrate the bad-deploy failure and recovery using the local ASGI app."""

from __future__ import annotations

from fastapi.testclient import TestClient

from target_app.app import app
from target_app.state import set_scenario


def main() -> int:
    client = TestClient(app)
    try:
        set_scenario("bad_deploy")
        failed = client.post("/checkout", json={"items": [{"price": 299}]})
        if failed.status_code != 500:
            raise RuntimeError(f"Expected injected failure, received HTTP {failed.status_code}.")
        set_scenario(None)
        recovered = client.post("/checkout", json={"items": [{"price": 299}]})
        if recovered.status_code != 200:
            raise RuntimeError(f"Expected healthy checkout after recovery, received HTTP {recovered.status_code}.")
        print("Bad-deploy demo passed: injected checkout failed (500), healed checkout succeeded (200).")
        return 0
    finally:
        set_scenario(None)


if __name__ == "__main__":
    raise SystemExit(main())
