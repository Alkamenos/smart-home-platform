"""
Test for release mechanism - FSM can release devices via action functions.

This test verifies:
1. FSM captures a device with priority 20.
2. Device appears in active_intents.
3. Emulating schedule_end event triggers release_device action.
4. dispatcher.release() is called and device is removed from active_intents.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import asyncio
import os
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    CommandDispatcher,
    CommandIntent,
    FSMDefinition,
    FSMEngine,
    Registry,
    Transition,
    release_device,
    turn_on_night_light,
)


class MockHAAdapter:
    """Mock HAAdapter for testing."""

    def __init__(self):
        self.call_service_calls: list[dict[str, Any]] = []
        self.call_service_async = AsyncMock()

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Mock call_service that records calls."""
        self.call_service_calls.append(
            {
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "data": data or {},
                "trace_id": trace_id,
            }
        )
        return True


@pytest.fixture
def mock_ha_adapter():
    """Create a mock HAAdapter."""
    return MockHAAdapter()


@pytest.fixture
def dispatcher(mock_ha_adapter):
    """Create a CommandDispatcher with mock adapter."""
    return CommandDispatcher(ha_adapter=mock_ha_adapter, middlewares=[])


@pytest.fixture
def fsm_engine(dispatcher):
    """Create an FSMEngine with dispatcher."""
    engine = FSMEngine(command_dispatcher=dispatcher)
    return engine


@pytest.fixture
def registry():
    """Create a Registry with action handlers."""
    registry = Registry()
    registry.register_action("turn_on_night_light", turn_on_night_light)
    registry.register_action("release_device", release_device)
    return registry


class TestReleaseMechanism:
    """Tests for FSM release mechanism."""

    @pytest.mark.asyncio
    async def test_fsm_captures_device_with_priority_20(
        self, fsm_engine, dispatcher, mock_ha_adapter, registry
    ):
        """
        Test: FSM captures a device with priority 20 and device appears in active_intents.
        """
        # Register FSM definition
        fsm_def = FSMDefinition(
            entity_id="light.hallway__night_light_20",
            initial_state="OFF",
            states=("OFF", "ON_NIGHT"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_NIGHT",
                    trigger="motion_detected",
                    action="turn_on_night_light",
                ),
            ),
            params={"brightness": 10},
            target_device_id="light.hallway",
        )
        fsm_engine.register_definition(fsm_def)

        # Register actions in engine
        for name in ["turn_on_night_light", "release_device"]:
            fn = registry.get_action(name)
            if fn:
                fsm_engine.register_action(name, fn)

        # Trigger motion_detected to capture the device
        result = await fsm_engine.trigger(
            "light.hallway__night_light_20",
            "motion_detected",
            external_ctx={"priority": 20, "source": "night_light"},
        )

        # Verify transition occurred
        assert result is True

        # Verify device is in active_intents
        assert "light.hallway" in dispatcher.active_intents
        assert dispatcher.active_intents["light.hallway"].priority == 20
        assert dispatcher.active_intents["light.hallway"].source == "night_light"

        # Verify HAAdapter was called
        assert len(mock_ha_adapter.call_service_calls) == 1

    @pytest.mark.asyncio
    async def test_schedule_end_releases_device(
        self, fsm_engine, dispatcher, mock_ha_adapter, registry
    ):
        """
        Test: Emulating schedule_end event triggers release_device action
        and device is removed from active_intents.
        """
        # Register FSM definition with schedule_end transition
        fsm_def = FSMDefinition(
            entity_id="light.hallway__night_light_20",
            initial_state="OFF",
            states=("OFF", "ON_NIGHT"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_NIGHT",
                    trigger="motion_detected",
                    action="turn_on_night_light",
                ),
                Transition(
                    from_state="ON_NIGHT",
                    to_state="OFF",
                    trigger="schedule_end",
                    action="release_device",
                ),
            ),
            params={"brightness": 10},
            target_device_id="light.hallway",
        )
        fsm_engine.register_definition(fsm_def)

        # Register actions in engine
        for name in ["turn_on_night_light", "release_device"]:
            fn = registry.get_action(name)
            if fn:
                fsm_engine.register_action(name, fn)

        # Step 1: Capture device with motion_detected
        result = await fsm_engine.trigger(
            "light.hallway__night_light_20",
            "motion_detected",
            external_ctx={"priority": 20, "source": "night_light"},
        )
        assert result is True
        assert "light.hallway" in dispatcher.active_intents

        # Step 2: Emulate schedule_end event
        result = await fsm_engine.trigger(
            "light.hallway__night_light_20",
            "schedule_end",
            external_ctx={"priority": 20, "source": "night_light"},
        )

        # Verify transition occurred
        assert result is True

        # Verify device is released from active_intents
        assert "light.hallway" not in dispatcher.active_intents

    @pytest.mark.asyncio
    async def test_release_device_action_calls_dispatcher_release(
        self, fsm_engine, dispatcher, mock_ha_adapter, registry
    ):
        """
        Test: release_device action correctly calls dispatcher.release().
        """
        # Manually submit an intent first
        intent = CommandIntent(
            device_id="light.test",
            domain="light",
            service="turn_on",
            data={},
            priority=20,
            source="test_source",
        )
        await dispatcher.submit(intent)

        # Verify device is captured
        assert "light.test" in dispatcher.active_intents

        # Create mock state and context for release_device action
        from core import State

        state = State(current_state="ON", entered_at=asyncio.get_event_loop().time(), context={})
        context = {
            "dispatcher": dispatcher,
            "target_device_id": "light.test",
            "source": "test_source",
        }

        # Call release_device action
        release_device(state, context)

        # Verify device is released
        assert "light.test" not in dispatcher.active_intents

    @pytest.mark.asyncio
    async def test_full_scenario_capture_and_release(
        self, fsm_engine, dispatcher, mock_ha_adapter, registry
    ):
        """
        Full scenario test:
        1. FSM captures device with priority 20.
        2. Device is in active_intents.
        3. schedule_end event triggers release.
        4. dispatcher.release() is called.
        5. Device is removed from active_intents.
        """
        # Register FSM definition
        fsm_def = FSMDefinition(
            entity_id="light.bedroom__night_light_20",
            initial_state="OFF",
            states=("OFF", "ON_NIGHT"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_NIGHT",
                    trigger="motion_detected",
                    action="turn_on_night_light",
                ),
                Transition(
                    from_state="ON_NIGHT",
                    to_state="OFF",
                    trigger="schedule_end",
                    action="release_device",
                ),
            ),
            params={"brightness": 10},
            target_device_id="light.bedroom",
        )
        fsm_engine.register_definition(fsm_def)

        # Register actions
        for name in ["turn_on_night_light", "release_device"]:
            fn = registry.get_action(name)
            if fn:
                fsm_engine.register_action(name, fn)

        # Step 1: Capture device
        result = await fsm_engine.trigger(
            "light.bedroom__night_light_20",
            "motion_detected",
            external_ctx={"priority": 20, "source": "night_light"},
        )
        assert result is True
        assert "light.bedroom" in dispatcher.active_intents
        assert dispatcher.active_intents["light.bedroom"].priority == 20

        # Store initial call count
        initial_calls = len(mock_ha_adapter.call_service_calls)

        # Step 2: Release via schedule_end
        result = await fsm_engine.trigger(
            "light.bedroom__night_light_20",
            "schedule_end",
            external_ctx={"priority": 20, "source": "night_light"},
        )
        assert result is True

        # Verify device is released
        assert "light.bedroom" not in dispatcher.active_intents

        # Verify no additional HA calls were made during release
        # (release_device doesn't call HA, it just releases the intent)
        assert len(mock_ha_adapter.call_service_calls) == initial_calls


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
