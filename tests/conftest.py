"""
Global test configuration and fixtures for Smart Home FSM Platform tests.

This module sets up:
- Python path for imports from src/
- Common pytest fixtures
- Mock configurations
"""

import sys
from pathlib import Path

import pytest

# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


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
