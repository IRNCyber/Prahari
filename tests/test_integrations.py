from agent.integrations.deployment import DeploymentClient
from agent.integrations.notifications import SlackNotifier, TelegramNotifier
from agent.integrations.sentry import SentryClient


def test_notifiers_refuse_empty_credentials(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not SlackNotifier().configured()
    assert not TelegramNotifier().configured()


def test_sentry_accepts_dsn_shape() -> None:
    assert SentryClient("https://key@example.ingest.sentry.io/1").configured()


def test_deployment_stays_disabled_without_token(monkeypatch) -> None:
    monkeypatch.delenv("DEPLOYMENT_TOKEN", raising=False)
    assert DeploymentClient().readiness()["enabled"] is False
