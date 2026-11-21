"""Explicit notification clients. Calls occur only when send() is invoked."""

from __future__ import annotations

import os

import httpx


class SlackNotifier:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("SLACK_WEBHOOK_URL", "")

    def configured(self) -> bool:
        return self.url.startswith("https://hooks.slack.com/")

    def send(self, text: str) -> None:
        if not self.configured():
            raise RuntimeError("SLACK_WEBHOOK_URL is not configured.")
        response = httpx.post(self.url, json={"text": text}, timeout=15)
        response.raise_for_status()


class TelegramNotifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.configured():
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required.")
        response = httpx.post(f"https://api.telegram.org/bot{self.token}/sendMessage", json={"chat_id": self.chat_id, "text": text}, timeout=15)
        response.raise_for_status()
