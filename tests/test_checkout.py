from fastapi.testclient import TestClient

from target_app.app import app
from target_app.state import set_scenario

client = TestClient(app)


def setup_function() -> None:
    set_scenario(None)


def teardown_function() -> None:
    set_scenario(None)


def test_health_is_healthy() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_products_are_listed() -> None:
    response = client.get("/products")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_checkout_without_discount_succeeds_when_healthy() -> None:
    response = client.post("/checkout", json={"items": [{"price": 299, "quantity": 1}]})
    assert response.status_code == 200
    assert response.json()["total"] == 299


def test_bad_deploy_regression_is_observable() -> None:
    set_scenario("bad_deploy")
    response = client.post("/checkout", json={"items": [{"price": 299}]})
    assert response.status_code == 500
