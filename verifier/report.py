from __future__ import annotations

from dataclasses import asdict, dataclass

from agent.tools import LocalTools
from target_app.state import read_state


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
    scenario = read_state().get("scenario")
    return VerificationReport(bool(tests["passed"]), scenario is None, scenario is None,
                              ["pytest suite completed", "fault state is healthy" if scenario is None else f"active scenario: {scenario}"])
