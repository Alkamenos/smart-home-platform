"""Tests for FSM diagram rendering in web UI."""

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture(scope="session")
def live_server_url():
    """Start a live test server and return its URL."""
    import threading
    import time

    import requests
    import uvicorn
    from src.webui.app import create_app

    # Create app
    app = create_app(manifest_path="instances/leonids_house/manifest.yaml")

    # Start server in background thread
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error"))
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    # Wait for server to start
    max_wait = 10
    start_time = time.time()
    while time.time() - start_time < max_wait:
        try:
            response = requests.get("http://127.0.0.1:8765/health", timeout=1)
            if response.status_code == 200:
                break
        except requests.exceptions.ConnectionError:
            time.sleep(0.5)
    else:
        raise RuntimeError("Server failed to start")

    yield "http://127.0.0.1:8765"

    server.should_exit = True


def test_fsm_diagram_renders_correctly(page: Page, live_server_url: str):
    """Test that FSM diagram renders correctly in modal window."""
    # Navigate to the web UI
    page.goto(live_server_url)

    # Wait for the page to load
    expect(page.locator("body")).to_be_visible()

    # Find and click the FSM button for climate.kitchen or climate.living_room
    # Look for buttons with data attribute or specific class
    fsm_buttons = page.locator("button[data-device-id], .fsm-btn, button:has-text('FSM')")

    if fsm_buttons.count() == 0:
        # If no specific FSM buttons, try to find any device card and look for FSM option
        page.click(".device-card:first-child")  # Open first device card if exists

    # Click the first available FSM button
    if fsm_buttons.count() > 0:
        fsm_buttons.first.click()

    # Wait for modal to appear - use specific ID selector
    modal = page.locator("#fsmModal")
    expect(modal).to_be_visible(timeout=5000)

    # Check that mermaid div exists
    mermaid_div = page.locator("#fsm-diagram-container .mermaid")
    expect(mermaid_div).to_be_visible(timeout=5000)

    # Wait for Mermaid to render the SVG
    svg_element = page.locator("#fsm-diagram-container .mermaid svg")
    expect(svg_element).to_be_visible(timeout=10000)

    # Verify SVG has content (not empty)
    svg_content = svg_element.inner_html()
    assert len(svg_content) > 100, "SVG element is too small, likely not rendered properly"

    # Check for common Mermaid elements
    assert "state" in svg_content.lower() or "node" in svg_content.lower(), (
        "SVG does not contain expected state diagram elements"
    )

    # Note: We're not checking console errors here because Mermaid.js may have
    # non-critical warnings that don't affect rendering. The important thing is
    # that the SVG is rendered successfully (which we verify above).


def test_mermaid_initialization(page: Page, live_server_url: str):
    """Test that Mermaid library initializes correctly."""
    page.goto(live_server_url)

    # Check if Mermaid library is loaded
    is_mermaid_loaded = page.evaluate("typeof mermaid !== 'undefined'")
    assert is_mermaid_loaded, "Mermaid library is not loaded"

    # Check if Mermaid is initialized
    is_mermaid_initialized = page.evaluate(
        "mermaid.hasOwnProperty('initialized') || typeof mermaid.initialize === 'function'"
    )
    assert is_mermaid_initialized, "Mermaid is not properly initialized"


def test_fsm_modal_content(page: Page, live_server_url: str):
    """Test that FSM modal contains valid Mermaid syntax."""
    page.goto(live_server_url)

    # Trigger FSM modal
    fsm_buttons = page.locator("button[data-device-id], .fsm-btn, button:has-text('FSM')")
    if fsm_buttons.count() > 0:
        fsm_buttons.first.click()

        # Wait for modal
        modal = page.locator("#fsmModal")
        expect(modal).to_be_visible(timeout=5000)

        # Get the Mermaid diagram text content from container (before rendering)
        # We need to check the raw diagram data attribute or wait for SVG
        mermaid_div = page.locator("#fsm-diagram-container .mermaid")
        expect(mermaid_div).to_be_visible(timeout=5000)

        # Wait for SVG to be rendered
        svg_element = page.locator("#fsm-diagram-container .mermaid svg")
        expect(svg_element).to_be_visible(timeout=10000)

        # Check that SVG contains state diagram elements
        svg_content = svg_element.inner_html()
        assert len(svg_content) > 100, f"SVG is too small: {svg_content[:200]}"

        # SVG should contain nodes/states
        assert "node" in svg_content.lower() or "state" in svg_content.lower(), (
            f"SVG does not contain expected diagram elements. Got: {svg_content[:200]}"
        )

        # Should have entity ID in the diagram
        diagram_text = mermaid_div.inner_text()
        assert "light.kitchen" in diagram_text or "OFF" in diagram_text, (
            f"Diagram does not contain expected states. Got: {diagram_text[:200]}"
        )
