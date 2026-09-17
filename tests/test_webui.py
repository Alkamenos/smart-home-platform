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
