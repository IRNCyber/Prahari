from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx

from agent.tools import LocalTools
from prahari.store import record_verification
from target_app.state import read_state
from traffic.replay import replay


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


@dataclass
class VerificationReport:
    suite_green: bool
    regression_proven: bool
    replay_baseline: bool
    details: list[str]

    @property
    def passed(self) -> bool:
        return self.suite_green and self.regression_proven and self.replay_baseline

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "passed": self.passed}


def verify() -> VerificationReport:
    tests = LocalTools().run_tests()
    regression = LocalTools().run_tests_for("tests/test_checkout.py::test_bad_deploy_regression_is_observable")
    scenario = read_state().get("scenario")
    base_url = __import__("os").getenv("STAGING_BASE_URL", "http://localhost:8000")
    try:
        replay_result = replay(base_url)
        replay_passed = _replay_passed(replay_result)
    except (httpx.HTTPError, OSError, ValueError) as error:
        replay_passed = False
        replay_result = {"error": type(error).__name__, "message": str(error)[:300]}
    report = VerificationReport(
        bool(tests["passed"]),
        bool(regression["passed"]),
        bool(replay_passed and scenario is None),
        [
            "pytest suite completed" if tests["passed"] else f"pytest failed: {tests['output']}",
            "dedicated regression test passed" if regression["passed"] else "dedicated regression test failed",
            "fault state is healthy" if scenario is None else f"active scenario: {scenario}",
            f"traffic replay: {replay_result}",
        ],
    )
    report_data = report.to_dict()
    report_data["test_output"] = tests["output"]
    report_data["regression_output"] = regression["output"]
    report_data["replay"] = replay_result
    record_verification(report_data)
    return report
