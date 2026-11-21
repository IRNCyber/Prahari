from __future__ import annotations

from target_app.state import set_scenario

SCENARIOS = {"bad_deploy", "config", "slow_query", "dep_outage"}


def inject(name: str) -> dict[str, object]:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {name}. Choose one of {sorted(SCENARIOS)}")
    return set_scenario(name)


def heal() -> dict[str, object]:
    return set_scenario(None)
