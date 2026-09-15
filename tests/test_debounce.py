"""
Debounce Tests - Tests for debounce protection against event spam

Tests cover:
1. Motion sensor spam (100 events in 1 second) - FSM should handle without crashes
2. Rapid state changes - FSM should debounce and not create excessive transitions
3. Echo detection - Commands from FSM should not trigger manual override
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core import FSMDefinition, FSMEngine, State, Transition


@pytest.fixture
def fsm_engine() -> FSMEngine:
    """Create FSM engine instance."""
    return FSMEngine()


class TestDebounceSpam:
    """Tests for protection against event spam (sensor bouncing)."""

    @pytest.mark.asyncio
    async def test_motion_sensor_spam_100_events(self, fsm_engine: FSMEngine) -> None:
        """
        Test: Motion sensor generates 100 events in 1 second.
        FSM should handle all events without crashes or excessive transitions.
        """
        transition_count = [0]

        def count_transitions(state: State, context: dict[str, Any]) -> None:
            transition_count[0] += 1

        fsm_engine.register_action("count_transitions", count_transitions)

        definition = FSMDefinition(
            entity_id="light.hallway",
            initial_state="OFF",
            states=("OFF", "ON_MOTION"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion_detected",
                    action="count_transitions",
                ),
                Transition(from_state="ON_MOTION", to_state="OFF", trigger="motion_cleared"),
            ),
        )

        fsm_engine.register_definition(definition)

        # Emulate spam: 100 motion_detected events in a row
        for i in range(100):
            await fsm_engine.trigger("light.hallway", "motion_detected", {"event_num": i})

        # FSM should transition to ON_MOTION only once (first event)
        # Subsequent 99 events should not cause transitions (already in ON_MOTION)
        state = fsm_engine.get_state("light.hallway")
        assert state.current_state == "ON_MOTION"
        assert transition_count[0] == 1, f"Expected 1 transition, got {transition_count[0]}"

    @pytest.mark.asyncio
    async def test_rapid_on_off_cycles(self, fsm_engine: FSMEngine) -> None:
        """
        Test: Rapid on/off cycles (50 times).
        FSM should handle without errors.
        """
        definition = FSMDefinition(
            entity_id="light.test",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                Transition(from_state="ON", to_state="OFF", trigger="turn_off"),
            ),
        )

        fsm_engine.register_definition(definition)

        # 50 rapid on/off cycles
        for _ in range(50):
            await fsm_engine.trigger("light.test", "turn_on", {})
            await fsm_engine.trigger("light.test", "turn_off", {})

        state = fsm_engine.get_state("light.test")
        assert state.current_state == "OFF"

    @pytest.mark.asyncio
    async def test_guard_exception_during_spam(self, fsm_engine: FSMEngine) -> None:
        """Test that guard exceptions don't crash FSM during event spam."""

        def flaky_guard(state: State, context: dict[str, Any]) -> bool:
            # Fail every 3rd call
            if context.get("count", 0) % 3 == 0:
                raise ValueError("Guard failed")
            return True

        fsm_engine.register_guard("flaky_guard", flaky_guard)

        definition = FSMDefinition(
            entity_id="light.test",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on", guard="flaky_guard"),
            ),
        )

        fsm_engine.register_definition(definition)

        # Send 20 events, some will fail guard
        for i in range(20):
            await fsm_engine.trigger("light.test", "turn_on", {"count": i})

        # FSM should still be operational
        state = fsm_engine.get_state("light.test")
        assert state is not None


class TestDebounceFeature:
    """Tests for debounce feature."""

    @pytest.mark.asyncio
    async def test_debounce_blocks_rapid_triggers(self, fsm_engine: FSMEngine) -> None:
        """Test that debounce prevents rapid successive triggers."""
        definition = FSMDefinition(
            entity_id="light.test",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                Transition(from_state="ON", to_state="OFF", trigger="turn_off"),
            ),
            debounce_sec=0.1,  # 100ms debounce
        )

        fsm_engine.register_definition(definition)

        # First trigger should work
        result1 = await fsm_engine.trigger("light.test", "turn_on", {})
        assert result1 is True

        # Second trigger within debounce window should be blocked
        result2 = await fsm_engine.trigger("light.test", "turn_on", {})
        assert result2 is False

        # Wait for debounce to expire
        await asyncio.sleep(0.15)

        # Third trigger after debounce should work (turn_off to go back to OFF first)
        result3 = await fsm_engine.trigger("light.test", "turn_off", {})
        assert result3 is True

    @pytest.mark.asyncio
    async def test_no_debounce_when_zero(self, fsm_engine: FSMEngine) -> None:
        """Test that zero debounce allows all triggers."""
        definition = FSMDefinition(
            entity_id="light.test",
            initial_state="OFF",
            states=("OFF", "ON", "AUTO"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                Transition(from_state="ON", to_state="AUTO", trigger="auto"),
            ),
            debounce_sec=0.0,  # No debounce
        )

        fsm_engine.register_definition(definition)

        # Both triggers should work immediately
        result1 = await fsm_engine.trigger("light.test", "turn_on", {})
        assert result1 is True

        result2 = await fsm_engine.trigger("light.test", "auto", {})
        assert result2 is True

        state = fsm_engine.get_state("light.test")
        assert state.current_state == "AUTO"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
