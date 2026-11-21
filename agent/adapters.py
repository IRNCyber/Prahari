"""Replaceable connector contracts; local adapters are used by default."""

from __future__ import annotations

from typing import Protocol


class MetricsAdapter(Protocol):
    def query(self, metric: str, window: str) -> dict[str, object]: ...


class LogAdapter(Protocol):
    def query(self, service: str, since: str) -> dict[str, object]: ...


class DeployAdapter(Protocol):
    def recent(self, count: int) -> dict[str, object]: ...


class NotificationAdapter(Protocol):
    def send(self, message: str) -> None: ...


class NullNotifier:
    def send(self, message: str) -> None:
        return None
