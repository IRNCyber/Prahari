from agent.integrations.koyeb import KoyebConfig


def test_koyeb_config_reads_service_ids(monkeypatch) -> None:
    monkeypatch.setenv("KOYEB_API_TOKEN", "token")
    monkeypatch.setenv("KOYEB_STAGING_SERVICE_ID", "staging")
    monkeypatch.setenv("KOYEB_PRODUCTION_SERVICE_ID", "production")
    assert KoyebConfig.from_environment().production_service_id == "production"
