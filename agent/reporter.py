from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import httpx

from agent.integrations.github import GitHubClient, GitHubConfig
from agent.integrations.notifications import (
    PagerDutyNotifier,
    SlackNotifier,
    TelegramNotifier,
)
from agent.integrations.sentry import SentryClient
from agent.tools import LocalTools
from prahari.atomic import atomic_write_text
from prahari.store import _redact, audit


class Notifier(Protocol):
    def configured(self) -> bool: ...

    def send(self, text: str) -> None: ...


def create_pr(diagnosis: str, verification: dict[str, object], patch: dict[str, object] | None = None) -> dict[str, object]:
    diagnosis = str(_redact(diagnosis))
    verification = _redact(verification)
    body = "\n".join([
        "## Summary", diagnosis,
        "## Root cause", diagnosis,
        "## Evidence", "See `artifacts/incident_trace.json`.",
        "## Verification", str(verification),
        "## Risk", "Local sample-service demonstration only.",
        "## Rollback", "Clear the injected scenario with `python main.py heal`.",
    ])
    title = "Prahari: verified incident remediation"
    if patch and patch.get("branch") and patch.get("worktree") and os.getenv("GITHUB_TOKEN"):
        client = GitHubClient(GitHubConfig.from_environment())
        try:
            client.push_branch(str(patch["branch"]), str(patch["worktree"]))
            result = client.create_pull_request(str(patch["branch"]), title, body)
        finally:
            client.close()
    else:
        result = LocalTools().open_pr(title, body)
    postmortem = Path(__file__).resolve().parents[1] / "artifacts" / "postmortem.md"
    atomic_write_text(postmortem, "# Blameless postmortem\n\n## Summary\n" + diagnosis + "\n\n## Verification\n" + str(verification))
    audit("postmortem_created", {"path": str(postmortem)}, actor="reporter")
    message = f"Prahari: verified remediation awaiting approval — {diagnosis}"
    notifiers: list[tuple[str, Notifier]] = [
        ("slack", SlackNotifier()),
        ("telegram", TelegramNotifier()),
        ("pagerduty", PagerDutyNotifier()),
    ]
    delivery = [
        {"channel": name, "status": "configured_not_sent"}
        for name, notifier in notifiers
        if notifier.configured()
    ]
    if SentryClient().configured():
        delivery.append({"channel": "sentry", "status": "configured"})
    if os.getenv("PRAHARI_SEND_NOTIFICATIONS", "false").lower() == "true":
        delivery = []
        for name, notifier in notifiers:
            if not notifier.configured():
                continue
            try:
                notifier.send(message)
            except (httpx.HTTPError, RuntimeError) as error:
                delivery.append({"channel": name, "status": "failed", "error": type(error).__name__})
            else:
                delivery.append({"channel": name, "status": "sent"})
    audit("external_notification_delivery", {"channels": delivery}, actor="reporter")
    result["notifications"] = delivery
    return result
