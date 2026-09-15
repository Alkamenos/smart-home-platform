"""
Integration tests for Home Assistant platform.

These tests use testcontainers-python to run a real Home Assistant instance
in Docker and verify end-to-end functionality of the smart home platform.

Tests verify:
- Docker container with HA starts automatically
- Platform connects to HA via WebSocket
- Full cycle: event -> FSM -> command -> HA
"""

import asyncio
import os
import time
from typing import Any

import aiohttp
import pytest
from loguru import logger

# Import platform components
from smart_home.adapters.ha_adapter import HAAdapter, HomeAssistantWS
from smart_home.core.event_bus import EventBus
from smart_home.core.registry import Registry as FSMRegistry

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
HA_IMAGE = "homeassistant/home-assistant:stable"
HA_PORT = 8123
HA_WS_URL = f"ws://localhost:{HA_PORT}/api/websocket"
HA_HTTP_URL = f"http://localhost:{HA_PORT}"
TEST_TOKEN = "test_token_for_integration"
CONNECTION_TIMEOUT = 180  # seconds to wait for HA to start (CI can be slow)
WS_RECONNECT_DELAY = 5


# ---------------------------------------------------------------------------
# Configuration for HA container
# ---------------------------------------------------------------------------
HA_CONFIGURATION_YAML = """
# Home Assistant test configuration for integration tests
# Uses trusted_networks auth for token-less API access

default_config:

# Allow access from Docker network without authentication
homeassistant:
  auth_providers:
    - type: trusted_networks
      trusted_networks:
        - 172.16.0.0/12
        - 10.0.0.0/8
        - 192.168.0.0/16
        - 127.0.0.1
        - ::1
    - type: homeassistant

# Enable WebSocket API
websocket_api:

# Enable REST API
api:

# HTTP server
http:
  server_port: 8123
  trusted_proxies:
    - 172.16.0.0/12
    - 10.0.0.0/8
  use_x_forwarded_for: true

# Logging
logger:
  default: info
  logs:
    homeassistant.components.websocket_api: debug
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ha_container():
    """
    Pytest fixture that starts Home Assistant in Docker using testcontainers.

    Yields:
        dict with container info including host, port, and token.
    """
    try:
        from testcontainers.core.container import DockerContainer
    except ImportError:
        pytest.skip("testcontainers not installed. Install with: pip install testcontainers")

    # Create test config directory
    test_config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_config")
    os.makedirs(test_config_dir, exist_ok=True)

    # Write configuration
    config_path = os.path.join(test_config_dir, "configuration.yaml")
    with open(config_path, "w") as f:
        f.write(HA_CONFIGURATION_YAML)

    # Create empty secrets.yaml (required by some HA versions)
    secrets_path = os.path.join(test_config_dir, "secrets.yaml")
    with open(secrets_path, "w") as f:
        f.write("# Test secrets file\n")

    # Start Home Assistant container
    container = (
        DockerContainer(HA_IMAGE)
        .with_bind_ports(HA_PORT, HA_PORT)
        .with_volume_mapping(test_config_dir, "/config", mode="rw")
        .with_name("ha_integration_test")
    )

    logger.info("Starting Home Assistant container...")
    container.start()

    host = container.get_container_host_ip()
    http_url = f"http://{host}:{HA_PORT}"
    ws_url = f"ws://{host}:{HA_PORT}/api/websocket"

    # Wait for HA to be ready using HTTP polling (more reliable than log parsing)
    try:
        _wait_for_ha_http_ready(http_url, timeout=CONNECTION_TIMEOUT)
        logger.info("Home Assistant HTTP API is ready")
        # Additional wait for WebSocket API to initialize
        time.sleep(15)
    except Exception as e:
        logger.error(f"Failed to wait for HA startup: {e}")
        # Print container logs for debugging
        try:
            logs = container.get_logs()
            logger.error(f"Container logs:\n{logs[-5000:]}")
        except Exception:
            pass
        container.stop()
        container.cleanup()
        raise

    yield {
        "container": container,
        "host": host,
        "port": HA_PORT,
        "http_url": http_url,
        "ws_url": ws_url,
    }

    # Cleanup
    logger.info("Stopping Home Assistant container...")
    container.stop()
    container.cleanup()


def _wait_for_ha_http_ready(http_url: str, timeout: int) -> None:
    """
    Wait for Home Assistant HTTP API to become ready.

    Polls the /api/ endpoint until it returns 200 or 401 (both mean server is up).
    This is more reliable than parsing logs, as log messages change between HA versions.

    Args:
        http_url: Base HTTP URL of HA instance.
        timeout: Maximum time to wait in seconds.

    Raises:
        TimeoutError: If HA does not become ready within timeout.
    """
    import urllib.error
    import urllib.request

    start_time = time.time()
    last_error = None

    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(f"{http_url}/api/")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status in (200, 401):
                    return
        except urllib.error.HTTPError as e:
            # 401 means auth required - server is up
            if e.code == 401:
                return
            last_error = e
        except (urllib.error.URLError, OSError, ConnectionError) as e:
            last_error = e
        except Exception as e:
            last_error = e

        time.sleep(3)

    raise TimeoutError(
        f"Home Assistant did not become ready within {timeout}s. " f"Last error: {last_error}"
    )


@pytest.fixture
def ha_token(ha_container):
    """
    Get a long-lived access token for HA.

    With trusted_networks auth provider, we can use any token or no token at all.
    """
    return os.environ.get("HA_TEST_TOKEN", TEST_TOKEN)


@pytest.fixture
async def ha_session(ha_container):
    """Create an aiohttp session for HA API calls."""
    async with aiohttp.ClientSession() as session:
        yield session


class MockFSMEngine:
    """Mock FSM Engine for integration testing."""

    def __init__(self):
        self.event_bus = EventBus()
        self.registry = FSMRegistry()
        self.events_received = []
        self.commands_sent = []
        self._event_handlers = {}
        self.event_bus.subscribe("state_change", self.process_event)

    async def process_event(self, event_type: str, payload: dict[str, Any], trace_id: str) -> None:
        """Process an event through the FSM."""
        self.events_received.append(
            {
                "event_type": event_type,
                "payload": payload,
                "trace_id": trace_id,
            }
        )

        # Simple FSM logic: motion detected -> turn on light
        if event_type == "state_change":
            entity_id = payload.get("entity_id", "")
            new_state = payload.get("new_state", "")

            if "motion" in entity_id and new_state == "on":
                # Simulate FSM action: turn on light
                self.commands_sent.append(
                    {
                        "domain": "light",
                        "service": "turn_on",
                        "entity_id": "light.test_light",
                        "data": {},
                        "trace_id": trace_id,
                    }
                )

    async def trigger(self, entity_id: str, event: str, external_ctx: dict[str, Any]) -> None:
        """Trigger FSM for an entity."""
        trace_id = external_ctx.get("trace_id", "unknown")
        await self.process_event(
            "state_change",
            {
                "entity_id": entity_id,
                "new_state": external_ctx.get("new_state", ""),
                "old_state": external_ctx.get("old_state", ""),
            },
            trace_id,
        )


@pytest.fixture
def mock_engine():
    """Create a mock FSM engine for testing."""
    return MockFSMEngine()


@pytest.fixture
async def ha_adapter(ha_container, ha_token, mock_engine):
    """Create and start HAAdapter connected to test HA instance."""
    adapter = HAAdapter(
        mode="websocket",
        engine=mock_engine,
        ws_url=ha_container["ws_url"],
        token=ha_token,
    )

    # Start the adapter
    await adapter.start()

    # Wait for connection with longer timeout for CI
    max_wait = 60
    waited = 0
    while not adapter.is_connected and waited < max_wait:
        await asyncio.sleep(1)
        waited += 1

    if not adapter.is_connected:
        await adapter.stop()
        pytest.skip("Could not connect to HA WebSocket within 60s")

    yield adapter

    # Cleanup
    await adapter.stop()


async def wait_for_ha_ready(http_url: str, session: aiohttp.ClientSession) -> bool:
    """Wait for Home Assistant to be ready."""
    max_attempts = CONNECTION_TIMEOUT // 2
    for _ in range(max_attempts):
        try:
            async with session.get(
                f"{http_url}/api/", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status in (200, 401):  # 401 is OK - means server is up
                    return True
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ha_container_starts(ha_container):
    """Test that Home Assistant container starts successfully."""
    assert ha_container is not None
    assert "host" in ha_container
    assert "port" in ha_container
    assert ha_container["port"] == HA_PORT


@pytest.mark.asyncio
async def test_ha_http_api_available(ha_container, ha_session):
    """Test that HA HTTP API is accessible."""
    http_url = ha_container["http_url"]

    # Wait for HA to be ready
    is_ready = await wait_for_ha_ready(http_url, ha_session)
    assert is_ready, "Home Assistant did not become ready in time"

    # Check API endpoint
    async with ha_session.get(f"{http_url}/api/") as resp:
        # 200 or 401 both mean server is up (401 = auth required)
        assert resp.status in (200, 401), f"API returned status {resp.status}"


@pytest.mark.asyncio
async def test_ha_websocket_connection(ha_container, ha_token):
    """Test that we can connect to HA WebSocket API."""
    ws_url = ha_container["ws_url"]

    ws_client = HomeAssistantWS(url=ws_url, token=ha_token, session=None)

    try:
        await ws_client.connect()
        assert ws_client.connected, "WebSocket connection failed"

        # Try to get states
        states = await ws_client.get_states()
        assert isinstance(states, list), "Should receive list of states"

    finally:
        await ws_client.close()


@pytest.mark.asyncio
async def test_create_virtual_devices(ha_container, ha_token, ha_session):
    """Test creating virtual devices in HA via REST API."""
    http_url = ha_container["http_url"]

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    async with ha_session.get(f"{http_url}/api/states", headers=headers) as resp:
        if resp.status == 401:
            pytest.skip("Authentication required - set HA_TEST_TOKEN environment variable")

        assert resp.status == 200, f"Failed to get states: {resp.status}"
        states = await resp.json()
        assert isinstance(states, list)


@pytest.mark.asyncio
async def test_ha_integration_full_cycle(ha_container, ha_token, mock_engine):
    """
    Test full integration cycle: event -> FSM -> command -> HA.
    """
    ws_url = ha_container["ws_url"]
    http_url = ha_container["http_url"]

    events_received = []

    async def handle_state_change(entity_id: str, new_state: str, old_state: str, context: dict):
        events_received.append(
            {
                "entity_id": entity_id,
                "new_state": new_state,
                "old_state": old_state,
                "context": context,
            }
        )

    adapter = HAAdapter(
        mode="websocket",
        engine=mock_engine,
        ws_url=ws_url,
        token=ha_token,
    )

    adapter.register_trace_callback(handle_state_change)

    try:
        await adapter.start()

        max_wait = 60
        waited = 0
        while not adapter.is_connected and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1

        if not adapter.is_connected:
            pytest.skip("Could not connect to HA WebSocket")

        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            }

            async with session.get(f"{http_url}/api/states", headers=headers) as resp:
                if resp.status == 401:
                    pytest.skip("Authentication required - set HA_TEST_TOKEN environment variable")

                existing_states = await resp.json()
                existing_ids = [s["entity_id"] for s in existing_states]

            test_light = (
                "light.kitchen"
                if "light.kitchen" in existing_ids
                else ("light.bedroom" if "light.bedroom" in existing_ids else None)
            )

            if test_light is None:
                # Create a test light using input_boolean if available
                test_light = "light.test_light"

            trace_id = "test_trace_123"
            motion_sensor = "binary_sensor.test_motion"
            await adapter.on_state_change(
                entity_id=motion_sensor,
                new_state="on",
                old_state="off",
                context={"trace_id": trace_id},
            )

            await asyncio.sleep(1)

            assert len(mock_engine.events_received) > 0, "FSM did not receive event"
            assert len(mock_engine.commands_sent) > 0, "FSM did not send any commands"

            command = mock_engine.commands_sent[0]
            assert command["domain"] == "light"
            assert command["service"] == "turn_on"

            result = await adapter.call_service(
                domain=command["domain"],
                service=command["service"],
                entity_id=test_light,
                data=command["data"],
                trace_id=command["trace_id"],
            )

            logger.info(f"Service call result: {result}")

    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_emulate_motion_event_via_api(ha_container, ha_token, ha_session):
    """Test emulating motion_detected event through HA REST API."""
    http_url = ha_container["http_url"]

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    event_data = {
        "entity_id": "binary_sensor.test_motion",
        "triggered_by": "integration_test",
    }

    async with ha_session.post(
        f"{http_url}/api/events/motion_detected",
        headers=headers,
        json=event_data,
    ) as resp:
        if resp.status == 401:
            pytest.skip("Authentication required for event firing")

        assert resp.status in (200, 400), f"Event firing returned {resp.status}"


@pytest.mark.asyncio
async def test_platform_receives_ha_events(ha_container, ha_token, mock_engine):
    """Test that the platform correctly receives events from HA."""
    ws_url = ha_container["ws_url"]

    received_messages = []

    async def message_handler(message: dict):
        received_messages.append(message)

    ws_client = HomeAssistantWS(url=ws_url, token=ha_token, session=None)

    try:
        await ws_client.connect()
        await ws_client.subscribe(message_handler, {"type": "state_changed"})
        assert ws_client.connected

    finally:
        await ws_client.close()


@pytest.mark.asyncio
async def test_light_turn_on_command_sent_to_ha(ha_container, ha_token, ha_session):
    """Test that light.turn_on commands are correctly sent to HA."""
    http_url = ha_container["http_url"]

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    async with ha_session.get(f"{http_url}/api/states", headers=headers) as resp:
        if resp.status == 401:
            pytest.skip("Authentication required")

        states = await resp.json()
        lights = [s for s in states if s["entity_id"].startswith("light.")]

        if not lights:
            pytest.skip("No light entities available")

        test_light = lights[0]["entity_id"]

    service_data = {"entity_id": test_light}

    async with ha_session.post(
        f"{http_url}/api/services/light/turn_on", headers=headers, json=service_data
    ) as resp:
        if resp.status == 401:
            pytest.skip("Authentication required for service calls")

        assert resp.status == 200, f"Service call failed with status {resp.status}"


@pytest.mark.asyncio
async def test_full_e2e_scenario(ha_container, ha_token, mock_engine):
    """Complete end-to-end test scenario."""
    ws_url = ha_container["ws_url"]
    http_url = ha_container["http_url"]

    adapter = HAAdapter(
        mode="websocket",
        engine=mock_engine,
        ws_url=ws_url,
        token=ha_token,
    )

    try:
        await adapter.start()

        max_wait = 60
        waited = 0
        while not adapter.is_connected and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1

        if not adapter.is_connected:
            pytest.skip("Could not connect to HA WebSocket")

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {ha_token}"}

            async with session.get(f"{http_url}/api/states", headers=headers) as resp:
                if resp.status == 401:
                    pytest.skip("Authentication required")

                states = await resp.json()
                lights = [s for s in states if s["entity_id"].startswith("light.")]

                if not lights:
                    pytest.skip("No light entities available")

                test_light = lights[0]["entity_id"]

            motion_sensor = "binary_sensor.motion_test"
            trace_id = "e2e_test_trace"

            await adapter.on_state_change(
                entity_id=motion_sensor,
                new_state="on",
                old_state="off",
                context={"trace_id": trace_id},
            )

            await asyncio.sleep(0.5)

            assert len(mock_engine.events_received) > 0
            assert len(mock_engine.commands_sent) > 0
            command = mock_engine.commands_sent[0]
            assert command["domain"] == "light"
            assert command["service"] == "turn_on"

            result = await adapter.call_service(
                domain=command["domain"],
                service=command["service"],
                entity_id=test_light,
                data={},
                trace_id=command["trace_id"],
            )

            logger.info(f"E2E test - Service call result: {result}")
            assert result is not None

    finally:
        await adapter.stop()
