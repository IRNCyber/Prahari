from agent.integrations.koyeb import platform_status


def test_koyeb_status_client_uses_public_summary(monkeypatch) -> None:
    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): return None
        def json(self): return self.payload

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def get(self, path):
            return Response({"page": {"status": "UP"}, "activeIncidents": [], "activeMaintenances": []} if path == "/summary.json" else {"components": [{"name": "API", "status": "OPERATIONAL"}]})

    monkeypatch.setattr("agent.integrations.koyeb.httpx.Client", Client)
    assert platform_status()["status"] == "UP"
