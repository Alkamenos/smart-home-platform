"""
Global test configuration and fixtures for Smart Home FSM Platform tests.

This module sets up:
- Python path for imports from src/
- Common pytest fixtures
- Mock configurations
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import sys
from pathlib import Path

import pytest


# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Import from core module directly (not smart_home package)


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy for asyncio tests."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    from unittest.mock import MagicMock

    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.exception = MagicMock()
    return logger


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for file-based tests."""
    return tmp_path


@pytest.fixture
def sample_manifest_data():
    """Sample manifest data for testing."""
    return {
        "instance": {
            "id": "test_house",
            "name": "Test House",
            "owner": "Test Owner",
            "created_at": "2024-01-01",
        },
        "version": 1,
        "devices": [
            {
                "type": "light_motion",
                "id": "light.kitchen",
                "name": "Kitchen Light",
                "room": "kitchen",
                "behaviors": [
                    {
                        "template": "lighting",
                        "priority": 10,
                        "params": {
                            "motion_sensor": "binary_sensor.kitchen_motion",
                            "motion_timeout_sec": 180,
                            "brightness": 255,
                        },
                    }
                ],
            }
        ],
        "automation_rules": {
            "global_manual_lockout_min": 60,
            "lighting": {
                "motion_enabled": True,
                "schedule_enabled": True,
                "manual_lockout_min": 60,
            },
        },
    }


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure browser context arguments for Playwright."""
    return {
        "ignore_https_errors": True,
        "viewport": {"width": 1280, "height": 720},
    }


@pytest.fixture(scope="session", autouse=True)
def webui_server():
    """Start Web UI server for testing.

    Yields control after server is ready, then stops it after tests complete.
    """
    import socket
    import subprocess
    import time

    # Check if server is already running
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("127.0.0.1", 8125))
    sock.close()

    if result == 0:
        # Server already running, don't manage it
        yield "http://127.0.0.1:8125"
        return

    # Start Web UI server
    project_root = Path(__file__).parent.parent
    env = {
        "PYTHONPATH": str(project_root),
        "MANIFEST_PATH": str(project_root / "instances" / "leonids_house" / "manifest.yaml"),
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
        ],
        cwd=str(project_root),
        env={**subprocess.os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    max_retries = 30
    for _i in range(max_retries):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 8125))
        sock.close()
        if result == 0:
            break
        time.sleep(0.5)

    yield "http://127.0.0.1:8125"

    # Cleanup
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
