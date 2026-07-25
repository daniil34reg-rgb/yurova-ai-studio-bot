from fastapi.testclient import TestClient

from portrait_bot.api import create_app


def test_health(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "environment": "test",
            "telegram_configured": False,
            "image_provider": "mock",
            "payment_provider": "mock",
        }
