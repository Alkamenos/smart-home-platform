"""Tests for Web UI module."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """Create test client for Web UI app with an isolated manifest copy.

    Web UI сохраняет манифест на диск (/devices/save), поэтому тесты работают
    с копией в tmp_path, а не с реальным instances/leonids_house/manifest.yaml.
    """
    from src.webui.app import create_app

    manifest_copy = tmp_path / "manifest.yaml"
    shutil.copy("instances/leonids_house/manifest.yaml", manifest_copy)
    app = create_app(manifest_path=str(manifest_copy))
    return TestClient(app)


def test_index_page_loads(client: TestClient):
    """Test that index page loads successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Smart Home - Manifest Editor" in response.content
    # Room cards must expose the ids that HTMX swaps target
    assert b'id="room-0"' in response.content
    # Modals targeted by the room/device edit buttons must exist
    assert b'id="edit-modal-content"' in response.content
    assert b'id="device-form-container"' in response.content


def test_health_endpoint(client: TestClient):
    """Health endpoint возвращает JSON-контракт готовности (FR-002, spec 003)."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}


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


def test_edit_device_loads_form(client: TestClient):
    """Test that edit device endpoint loads the device form."""
    response = client.get("/devices/0/light.kitchen/edit")
    assert response.status_code == 200
    assert b"Edit Device" in response.content
    assert b"light.kitchen" in response.content


def test_edit_device_not_found(client: TestClient):
    """Test editing non-existent device returns 404."""
    response = client.get("/devices/0/nonexistent.device/edit")
    assert response.status_code == 404


def test_save_device_updates_manifest(client: TestClient):
    """Test that saving device updates the manifest store."""
    # Save a device with modified name
    response = client.post(
        "/devices/save",
        data={
            "room_index": "0",
            "device_index": "0",
            "device_id": "light.kitchen",
            "device_type": "light",
            "device_name": "Updated Kitchen Light",
            "behavior_template_0": "lighting",
            "behavior_priority_0": "10",
            "behavior_params_0": "{}",
        },
    )
    assert response.status_code == 200
    assert b"saved successfully" in response.content.lower()


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


class TestFSMDiagram:
    """Tests for the FSM diagram endpoint and the Mermaid it produces."""

    def test_container_registers_fsm_definitions(self, client: TestClient):
        """Behaviors in the manifest are turned into real FSM definitions.

        Guards against silently registering nothing, which would leave the UI
        with nothing to draw while every request still returned 200.
        """
        definitions = client.app.state.container.fsm._definitions

        assert len(definitions) > 0, "no FSM definitions registered from the manifest"

    def test_diagram_renders_for_device_with_behaviors(self, client: TestClient):
        """A device with behaviors returns a populated Mermaid diagram."""
        response = client.get("/api/fsm/light.kitchen/diagram")

        assert response.status_code == 200
        diagram = response.json()["diagram"]
        assert diagram.startswith("stateDiagram-v2")
        assert "OFF" in diagram
        assert "ON_MOTION" in diagram
        # Every behavior of the device is represented.
        assert "light_kitchen_lighting_10" in diagram
        assert "light_kitchen_night_light_20" in diagram

    def test_diagram_uses_valid_mermaid_state_ids(self, client: TestClient):
        """State ids are sanitized, so raw dotted entity ids never act as ids."""
        diagram = client.get("/api/fsm/light.kitchen/diagram").json()["diagram"]

        state_ids = {
            line.split(":")[0].strip()
            for line in diagram.splitlines()
            if line.startswith("light_") or line.startswith("[*]")
        }
        assert state_ids, "no state ids parsed from diagram"
        for state_id in state_ids:
            assert "." not in state_id, f"illegal Mermaid state id: {state_id}"

    def test_diagram_marks_every_machine_as_initial(self, client: TestClient):
        """Each state machine gets its own entry transition from the start state."""
        diagram = client.get("/api/fsm/light.kitchen/diagram").json()["diagram"]

        assert diagram.count("[*] -->") == 2
        assert "[*] --> light_kitchen_lighting_10" in diagram
        assert "[*] --> light_kitchen_night_light_20" in diagram

    def test_diagram_does_not_alias_same_label_twice(self, client: TestClient):
        """A device with several behaviors must not reuse one Mermaid state alias."""
        diagram = client.get("/api/fsm/light.kitchen/diagram").json()["diagram"]

        assert "state 'light.kitchen' as" not in diagram

    def test_diagram_shows_named_guards(self, client: TestClient):
        """Guards are labelled with their template name, not an anonymous wrapper."""
        diagram = client.get("/api/fsm/light.kitchen/diagram").json()["diagram"]

        assert "guard_fn" not in diagram
        assert "[schedule]" in diagram

    def test_diagram_for_single_behavior_keeps_friendly_label(self, client: TestClient):
        """A lone state machine may carry the human-readable device name."""
        diagram = client.get("/api/fsm/fan.bathroom/diagram").json()["diagram"]

        assert "state 'fan.bathroom' as fan_bathroom_humidity_ventilation_5" in diagram
        assert "idle" in diagram
        assert "ventilating" in diagram

    def test_diagram_unknown_device_returns_404(self, client: TestClient):
        """Unknown or behavior-less devices get a clear 404, not an empty diagram."""
        response = client.get("/api/fsm/light.nonexistent/diagram")

        assert response.status_code == 404
        assert "error" in response.json()
