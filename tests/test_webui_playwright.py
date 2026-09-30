"""Playwright E2E tests for Web UI functionality.

Запускать ОТДЕЛЬНО от основного прогона (файл исключён из addopts в pyproject.toml):

    pytest tests/test_webui_playwright.py

Причина: session-фикстура playwright sync API держит event loop в состоянии
running на протяжении всей сессии — async-тесты и последующие pytest-файлы
падают с \"Runner.run() cannot be called from a running event loop\"
(см. Known Issue #13 в .ai/01_PROJECT_STATE.md). Тесты должны быть sync.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure browser context arguments."""
    return {
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
    }


@pytest.fixture(scope="session", autouse=True)
def start_webui_server():
    """Start the Web UI server for testing."""
    # Check if server is already running
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("127.0.0.1", 8125))
    sock.close()

    if result == 0:
        # Server already running
        yield
        return

    # Start server
    env = {
        "PYTHONPATH": str(Path(__file__).parent.parent),
        "MANIFEST_PATH": "instances/leonids_house/manifest.yaml",
    }

    process = subprocess.Popen(
        [
            "python",
            "-m",
            "uvicorn",
            "src.webui.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8125",
            "--reload",
        ],
        env={**subprocess.os.environ, **env},
    )

    # Wait for server to start
    time.sleep(3)

    yield

    # Cleanup
    process.terminate()
    process.wait(timeout=10)


class TestWebUIBasics:
    """Test basic Web UI functionality."""

    def test_index_page_loads(self, page):
        """Test that index page loads successfully."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Check page title
        title = page.title()
        assert "Smart Home" in title

        # Check for room cards
        room_cards = page.locator(".room-card").count()
        assert room_cards > 0

    def test_health_check_endpoint(self, page):
        """Test health check endpoint."""
        page.goto("http://127.0.0.1:8125/health")
        content = page.content()
        assert "healthy" in content.lower()


class TestDeviceManagement:
    """Test device management functionality."""

    def test_open_device_edit_form(self, page):
        """Test opening device edit form."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Find first device edit button
        edit_buttons = page.locator("button:has-text('Edit')").count()
        assert edit_buttons > 0

        # Click first edit button
        page.locator("button:has-text('Edit')").first.click()

        # Wait for modal to appear
        modal = page.locator("#deviceModal, [role='dialog']")
        modal.wait_for(state="visible", timeout=5000)

        # Check form elements
        assert page.locator('input[name="device_id"]').is_visible()
        assert page.locator('select[name="device_type"]').is_visible()

    def test_device_form_displays_room_selector(self, page):
        """Test that device form has room selector."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Open device edit form
        page.locator("button:has-text('Edit')").first.click()
        page.wait_for_load_state("networkidle")

        # Check for room selector
        room_select = page.locator('select[name="room_id"]')
        assert room_select.is_visible()

        # Check that room options are available
        options = room_select.locator("option").count()
        assert options > 1  # At least one room option

    def test_change_device_room(self, page):
        """Test changing device to different room."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Open device edit form
        page.locator("button:has-text('Edit')").first.click()
        page.wait_for_load_state("networkidle")

        # Get current room selection
        room_select = page.locator('select[name="room_id"]')
        current_room = room_select.input_value()

        # Select different room
        available_options = room_select.locator("option").count()
        if available_options > 2:
            room_select.locator("option").nth(2).click()
            page.wait_for_timeout(500)

            new_room = room_select.input_value()
            assert new_room != current_room, "Room selection should change"

            # Save device
            page.locator("button:has-text('Save Device')").click()
            page.wait_for_load_state("networkidle")

            # Reload page to verify change persisted
            page.reload()
            page.wait_for_load_state("networkidle")

            # Open same device again and verify it's in new room
            # (This requires finding the device in its new location)

    def test_add_device_to_room(self, page):
        """Test adding new device to a room."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Find "Add Device" button
        add_buttons = page.locator("button:has-text('Add Device')").count()
        assert add_buttons > 0

        # Click first "Add Device" button
        page.locator("button:has-text('Add Device')").first.click()
        page.wait_for_load_state("networkidle")

        # Fill device form
        page.locator('input[name="device_id"]').fill("test.newdevice")
        page.locator('select[name="device_type"]').select_option("light")
        page.locator('input[name="device_name"]').fill("Test Device")

        # Add behavior
        page.locator("button:has-text('Add Behavior')").click()
        page.wait_for_timeout(500)

        # Select template
        template_select = page.locator("select.behavior-template").last
        template_select.select_option("lighting")

        # Set priority
        page.locator('input[name="behavior_priority_0"]').fill("10")

        # Save device
        page.locator("button:has-text('Save Device')").click()
        page.wait_for_load_state("networkidle")

        # Wait for modal to close
        modal = page.locator("#deviceModal, [role='dialog']")
        modal.wait_for(state="hidden", timeout=5000)

        # Verify device appears in the room
        page.wait_for_timeout(1000)
        assert page.locator(":has-text('test.newdevice')").count() > 0


class TestBehaviorManagement:
    """Test behavior configuration."""

    def test_add_behavior_to_device(self, page):
        """Test adding behavior to device."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Open device edit form
        page.locator("button:has-text('Edit')").first.click()
        page.wait_for_load_state("networkidle")

        # Count behaviors before
        behaviors_before = page.locator(".behavior-item").count()

        # Add behavior
        page.locator("button:has-text('Add Behavior')").click()
        page.wait_for_timeout(500)

        # Count behaviors after
        behaviors_after = page.locator(".behavior-item").count()
        assert behaviors_after == behaviors_before + 1

    def test_expand_behavior_parameters(self, page):
        """Test expanding behavior parameters section."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Open device edit form
        page.locator("button:has-text('Edit')").first.click()
        page.wait_for_load_state("networkidle")

        # Find parameters section
        params_links = page.locator("a:has-text('Show Parameters')").count()
        if params_links > 0:
            page.locator("a:has-text('Show Parameters')").first.click()
            page.wait_for_timeout(300)

            # Check that parameters form is visible
            params_forms = page.locator(".params-form").count()
            assert params_forms > 0

    def test_remove_behavior_from_device(self, page):
        """Test removing behavior from device."""
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Open device edit form
        page.locator("button:has-text('Edit')").first.click()
        page.wait_for_load_state("networkidle")

        # Count behaviors before
        behaviors_before = page.locator(".behavior-item").count()

        if behaviors_before > 1:
            # Remove last behavior
            remove_buttons = page.locator("button:has-text('Remove')")
            remove_buttons.last.click()
            page.wait_for_timeout(300)

            # Count behaviors after
            behaviors_after = page.locator(".behavior-item").count()
            assert behaviors_after == behaviors_before - 1


class TestTemplateAPI:
    """Test template API functionality."""

    def test_templates_api_returns_list(self, page):
        """Test that /api/templates endpoint returns template list."""
        page.goto("http://127.0.0.1:8125/api/templates")

        # Get response
        response_text = page.content()
        templates = json.loads(response_text)

        assert isinstance(templates, list)
        assert len(templates) > 0
        assert any(t in templates for t in ["lighting", "climate_control"])

    def test_template_info_api(self, page):
        """Test that template info API returns correct data."""
        page.goto("http://127.0.0.1:8125/api/templates/lighting")

        response_text = page.content()
        template_info = json.loads(response_text)

        assert "name" in template_info
        assert template_info["name"] == "lighting"


class TestResponsiveness:
    """Test responsive design."""

    def test_mobile_layout(self, page):
        """Test mobile layout (375px width)."""
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Check that room cards are still visible
        room_cards = page.locator(".room-card").count()
        assert room_cards > 0

    def test_tablet_layout(self, page):
        """Test tablet layout (768px width)."""
        page.set_viewport_size({"width": 768, "height": 1024})
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Check that room cards are still visible
        room_cards = page.locator(".room-card").count()
        assert room_cards > 0

    def test_desktop_layout(self, page):
        """Test desktop layout (1920px width)."""
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto("http://127.0.0.1:8125/")
        page.wait_for_load_state("networkidle")

        # Check that room cards are visible
        room_cards = page.locator(".room-card").count()
        assert room_cards > 0
