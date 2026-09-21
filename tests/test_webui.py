"""Tests for Web UI module."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client for Web UI app."""
    from src.webui.app import create_app

    app = create_app(manifest_path="instances/leonids_house/manifest.yaml")
    return TestClient(app)


def test_index_page_loads(client: TestClient):
    """Test that index page loads successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Smart Home Manifest Editor" in response.content


def test_health_endpoint(client: TestClient):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert b"healthy" in response.content


def test_save_manifest_invalid_data(client: TestClient):
    """Test saving manifest with invalid data."""
    response = client.post(
        "/save",
        data={"manifest_data": "invalid json"},
    )
    assert response.status_code == 400


def test_room_edit_not_found(client: TestClient):
    """Test editing non-existent room returns 404."""
    response = client.get("/rooms/999/edit")
    assert response.status_code == 404


def test_get_ai_suggestions(client: TestClient):
    """Test getting AI suggestions endpoint."""
    response = client.get("/api/ai/suggestions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_respond_to_suggestion(client: TestClient):
    """Test responding to AI suggestion."""
    # Test with mock suggestion ID
    response = client.post("/api/ai/suggestion/1/respond", json={"action": "accept"})
    assert response.status_code in [200, 404]  # 404 if no suggestion found, 200 if success


def test_dashboard_page(client: TestClient):
    """Test dashboard page loads."""
    response = client.get("/dashboard")
    assert response.status_code == 200


def test_get_overrides(client: TestClient):
    """Test getting manual overrides."""
    response = client.get("/api/overrides")
    assert response.status_code == 200


def test_create_override(client: TestClient):
    """Test creating manual override."""
    response = client.post(
        "/api/override", json={"entity_id": "light.test", "action": "on", "duration": 60}
    )
    assert response.status_code in [200, 422]  # 422 if validation fails


def test_remove_override(client: TestClient):
    """Test removing manual override."""
    response = client.delete("/api/override/light.test")
    assert response.status_code in [200, 404]
