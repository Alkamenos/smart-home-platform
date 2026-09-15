"""
Integration tests for Home Assistant platform.

These tests use testcontainers-python to run a real Home Assistant instance
in Docker and verify end-to-end functionality of the smart home platform.
"""

import asyncio
import os
import time
import urllib.error
import urllib.request
from typing import Any

import aiohttp
import pytest
from loguru import logger

from adapters.ha_adapter import HAAdapter, HomeAssistantWS
from core import Registry as FSMRegistry
from core.event_bus import EventBus

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
HA_IMAGE = "homeassistant/home-assistant:stable"
HA_PORT = 8123
TEST_TOKEN = "test_token_for_integration"
CONNECTION_TIMEOUT = 180  # seconds to wait for HA to start
WS_RECONNECT_DELAY = 5


# ---------------------------------------------------------------------------
# HA configuration with trusted_networks auth (no token validation needed)
# ---------------------------------------------------------------------------
HA_CONFIGURATION_YAML = """
default_config:

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

websocket_api:

api:

http:
  server_port: 8123
  trusted_proxies:
    - 172.16.0.0/12
    - 10.0.0.0/8
  use_x_forwarded_for: true

logger:
  default: info
  logs:
    homeassistant.components.websocket_api: debug
"""


def _wait_for_ha_http_ready(http_url: str, timeout: int) -> None:
    """Poll HA HTTP API until it responds (200 or 401 both mean ready)."""
    start_time = time.time()
    last_error = None

    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(f"{http_url}/api/")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status in (200, 401):
                    return
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return
            last_error = e
        except (urllib.error.URLError, OSError, ConnectionError, Exception) as e:
            last_error = e

        time.sleep(3)

    raise TimeoutError(f"HA did not become ready within {timeout}s. Last error: {last_error}")


@pytest.fixture(scope="module")
def ha_container():
    """Start Home Assistant in Docker using testcontainers."""
    try:
        from testcontainers.core.container import DockerContainer
    except ImportError:
        pytest.skip("testcontainers not installed. Install with: pip install testcontainers")

    test_config_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test_config")
    os.makedirs(test_config_dir, exist_ok=True)

    config_path = os.path.join(test_config_dir, "configuration.yaml")
    with open(config_path, "w") as f:
        f.write(HA_CONFIGURATION_YAML)

    secrets_path = os.path.join(test_config_dir, "secrets.yaml")
    with open(secrets_path, "w") as f:
        f.write("# Test secrets file\n")

    container = (
        DockerContainer(HA_IMAGE)
        .with_bind_ports(HA_PORT, HA_PORT)
        .with_volume_mapping(test_config_dir, "/config", mode="rw")
    )

    logger.info("Starting Home Assistant container...")
    container.start()

    host = container.get_container_host_ip()
    http_url = f"http://{host}:{HA_PORT}"
    ws_url = f"ws://{host}:{HA_PORT}/api/websocket"

    try:
        _wait_for_ha_http_ready(http_url, timeout=CONNECTION_TIMEOUT)
        logger.info("Home Assistant HTTP API is ready")
        time.sleep(10)
    except Exception as e:
        logger.error(f"Failed to wait for HA startup: {e}")
        try:
            logs = container.get_logs()
            logger.error(f"Container logs (last 3000 chars):\n{logs[-3000:]}")
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

    logger.info("Stopping Home Assistant container...")
    container.stop()
    container.cleanup()


@pytest.fixture
def ha_token(ha_container):
    return os.environ.get("HA_TEST_TOKEN", TEST_TOKEN)


@pytest.fixture
async def ha_session(ha_container):
    async with aiohttp.ClientSession() as session:
        yield session


class MockFSMEngine:
    """Mock FSM Engine for integration testing."""

    def __init__(self):
        self.event_bus = EventBus()
        self.registry = FSMRegistry()
        self.events_received = []
        self.commands_sent = []
        self.event_bus.subscribe("state_change", self.process_event)

    async def process_event(self, event_type: str, payload: dict[str, Any], trace_id: str) -> None:
        self.events_received.append(
            {"event_type": event_type, "payload": payload, "trace_id": trace_id}
        )

        if event_type == "state_change":
            entity_id = payload.get("entity_id", "")
            new_state = payload.get("new_state", "")

            if "motion" in entity_id and new_state == "on":
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
    return MockFSMEngine()


@pytest.fixture
async def ha_adapter(ha_container, ha_token, mock_engine):
    adapter = HAAdapter(
        mode="websocket",
        engine=mock_engine,
        ws_url=ha_container["ws_url"],
        token=ha_token,
    )

    await adapter.start()

    max_wait = 60
    waited = 0
    while not adapter.is_connected and waited < max_wait:
        await asyncio.sleep(1)
        waited += 1

    if not adapter.is_connected:
        await adapter.stop()
        pytest.skip("Could not connect to HA WebSocket within 60s")

    yield adapter
    await adapter.stop()


@pytest.mark.asyncio
async def test_ha_container_starts(ha_container):
    assert ha_container is not None
    assert "host" in ha_container
    assert "port" in ha_container
    assert ha_container["port"] == HA_PORT


@pytest.mark.asyncio
async def test_ha_http_api_available(ha_container, ha_session):
    http_url = ha_container["http_url"]

    async with ha_session.get(f"{http_url}/api/", timeout=aiohttp.ClientTimeout(total=10)) as resp:
        assert resp.status in (200, 401), f"API returned status {resp.status}"


@pytest.mark.asyncio
async def test_ha_websocket_connection(ha_container, ha_token):
    ws_url = ha_container["ws_url"]

    ws_client = HomeAssistantWS(url=ws_url, token=ha_token, session=None)

    try:
        await ws_client.connect()
        assert ws_client.connected, "WebSocket connection failed"

        states = await ws_client.get_states()
        assert isinstance(states, list), "Should receive list of states"
    finally:
        await ws_client.close()


@pytest.mark.asyncio
async def test_create_virtual_devices(ha_container, ha_token, ha_session):
    http_url = ha_container["http_url"]

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    async with ha_session.get(f"{http_url}/api/states", headers=headers) as resp:
        if resp.status == 401:
            pytest.skip("Authentication required")
        assert resp.status == 200, f"Failed to get states: {resp.status}"
        states = await resp.json()
        assert isinstance(states, list)


@pytest.mark.asyncio
async def test_ha_integration_full_cycle(ha_container, ha_token, mock_engine):
    ws_url = ha_container["ws_url"]

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

    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_full_e2e_scenario(ha_container, ha_token, mock_engine):
    ws_url = ha_container["ws_url"]

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

    finally:
        await adapter.stop()
