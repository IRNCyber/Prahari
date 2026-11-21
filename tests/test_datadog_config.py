import os

from agent.integrations.datadog import DatadogConfig


def test_datadog_config_normalizes_api_url(monkeypatch) -> None:
    monkeypatch.setenv("DATADOG_API_KEY", "api")
    monkeypatch.setenv("DATADOG_APP_KEY", "app")
    monkeypatch.setenv("DATADOG_SITE", "https://api.datadoghq.eu")
    assert DatadogConfig.from_environment().api_url == "https://api.datadoghq.eu"
