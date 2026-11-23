"""Run candidate-branch tests in a network-isolated Docker container."""

from __future__ import annotations

import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from otel.tracing import traced

ROOT = Path(__file__).resolve().parents[1]


@traced("agent.verifier.isolated_tests")
def verify_worktree(worktree: str | Path, timeout_seconds: int = 600) -> dict[str, Any]:
    path = Path(worktree).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not path.is_dir() or temp_root not in path.parents or not (path.parent / ".git").exists():
        raise ValueError("Verification requires a Prahari Git worktree under the system temp directory.")

    revision = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    image = f"prahari-verifier:{uuid.uuid4().hex[:12]}"
    build = subprocess.run(
        ["docker", "build", "--file", str(ROOT / "verifier" / "Dockerfile"), "--tag", image, str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if build.returncode:
        return {"passed": False, "suite_green": False, "regression_proven": False, "replay_baseline": False, "stage": "build", "output": (build.stdout + build.stderr)[-8000:]}

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                "--env",
                "PRAHARI_DATA_DIR=/tmp/prahari",
                "--env",
                f"PRAHARI_REVISION={revision}",
                image,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        try:
            details = json.loads(result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            details = {"suite_green": False, "replay_baseline": False}
        return {
            **details,
            "passed": result.returncode == 0 and bool(details.get("passed")),
            "stage": "isolated_tests_and_replay",
            "exit_code": result.returncode,
            "output": (result.stdout + result.stderr)[-8000:],
        }
    finally:
        subprocess.run(["docker", "image", "rm", "--force", image], check=False, capture_output=True, text=True, timeout=60)
