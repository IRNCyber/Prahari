"""Runs the candidate test suite and recorded traffic against the sandboxed build."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from traffic.replay import record, replay

ROOT = Path(__file__).resolve().parents[1]


def _replay_passed(result: dict[str, object]) -> bool:
    error_rate = result.get("error_rate")
    latency = result.get("p95_latency_ms")
    return (
        isinstance(error_rate, (int, float))
        and not isinstance(error_rate, bool)
        and isinstance(latency, (int, float))
        and not isinstance(latency, bool)
        and error_rate <= 0.05
        and latency <= 1500
    )


def main() -> int:
    env = os.environ.copy()
    env["PRAHARI_DATA_DIR"] = "/tmp/prahari"
    env.pop("DATABASE_URL", None)
    server_log = Path(tempfile.gettempdir()) / "prahari-sandbox-server.log"
    with server_log.open("w", encoding="utf-8") as output:
        server = subprocess.Popen(
            [sys.executable, "main.py", "serve"],
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Candidate service exited before readiness: {server_log.read_text(encoding='utf-8')[-3000:]}")
            try:
                response = httpx.get("http://127.0.0.1:8000/health", timeout=1)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Candidate service did not become healthy within 30 seconds.")

        tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=240,
        )
        replay_file = Path(tempfile.gettempdir()) / "prahari-recorded-traffic.json"
        record(replay_file)
        replay_result = replay("http://127.0.0.1:8000", replay_file, os.getenv("PRAHARI_REVISION"))
        replay_baseline = _replay_passed(replay_result)
        passed = tests.returncode == 0 and replay_baseline
        print(json.dumps({
            "passed": passed,
            "suite_green": tests.returncode == 0,
            "test_output": (tests.stdout + tests.stderr)[-6000:],
            "replay": replay_result,
            "replay_baseline": replay_baseline,
        }))
        return 0 if passed else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
