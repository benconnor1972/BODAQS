"""Health endpoint smoke test."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bodaqs_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
