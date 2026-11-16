from fastapi.testclient import TestClient

from docent_api import __version__
from docent_api.main import app

client = TestClient(app)


def test_health_reports_ok_and_version() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_allows_the_web_origin() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
