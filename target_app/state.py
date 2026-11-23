from __future__ import annotations

from prahari.store import audit, get_state, set_state


def read_state() -> dict[str, object]:
    return get_state()


def set_scenario(scenario: str | None) -> dict[str, object]:
    state: dict[str, object] = {"scenario": scenario}
    set_state(state)
    audit("fault_state_changed", state, actor="fault-injector")
    return state
