from agent.integrations.render import RenderConfig


def test_render_config_reads_service_ids(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "key")
    monkeypatch.setenv("RENDER_STAGING_SERVICE_ID", "srv-staging")
    monkeypatch.setenv("RENDER_PRODUCTION_SERVICE_ID", "srv-production")
    assert RenderConfig.from_environment().staging_service_id == "srv-staging"
