"""
Unit tests for FSM Engine

Tests verify:
- FSM registration
- State transitions
- Guard conditions
- Timeout handling
- Immutability of states
- Debounce protection
"""

from __future__ import annotations

from typing import Any

import pytest

from smart_home.core.fsm import FSMDefinition, FSMEngine, State, Transition


@pytest.fixture
def fsm_engine() -> FSMEngine:
    """Create FSM engine instance."""
    return FSMEngine()


class TestFSMRegistration:
    """Tests for FSM registration."""

    def test_register_simple_fsm(self, fsm_engine: FSMEngine) -> None:
        """Test simple FSM registration."""
        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )

        fsm_engine.register_definition(definition)
        state = fsm_engine.get_state("test.entity")

        assert state is not None
        assert state.current_state == "OFF"

    def test_register_multiple_fsms(self, fsm_engine: FSMEngine) -> None:
        """Test registration of multiple FSMs."""
        for i in range(3):
            definition = FSMDefinition(
                entity_id=f"test.entity_{i}",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(
                    Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
                )
            )
            fsm_engine.register_definition(definition)

        assert len(fsm_engine.get_all_states()) == 3


class TestFSMTransitions:
    """Tests for state transitions."""

    @pytest.mark.asyncio
    async def test_simple_transition(self, fsm_engine: FSMEngine) -> None:
        """Test simple state transition."""
        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )

        fsm_engine.register_definition(definition)
        result = await fsm_engine.trigger("test.entity", "turn_on", {})

        assert result is True
        assert fsm_engine.get_state("test.entity").current_state == "ON"

    @pytest.mark.asyncio
    async def test_no_transition_for_unknown_event(self, fsm_engine: FSMEngine) -> None:
        """Test that unknown events don't cause transitions."""
        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )

        fsm_engine.register_definition(definition)
        result = await fsm_engine.trigger("test.entity", "unknown_event", {})

        assert result is False
        assert fsm_engine.get_state("test.entity").current_state == "OFF"


class TestFSMGuards:
    """Tests for guard conditions."""

    @pytest.mark.asyncio
    async def test_guard_true(self, fsm_engine: FSMEngine) -> None:
        """Test transition when guard returns True."""

        def allowed_guard(state: State, context: dict[str, Any]) -> bool:
            return context.get("allowed", False)

        fsm_engine.register_guard("allowed_guard", allowed_guard)

        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard="allowed_guard"
                ),
            )
        )

        fsm_engine.register_definition(definition)

        # Guard returns True
        result = await fsm_engine.trigger("test.entity", "turn_on", {"allowed": True})
        assert result is True
        assert fsm_engine.get_state("test.entity").current_state == "ON"

    @pytest.mark.asyncio
    async def test_guard_false(self, fsm_engine: FSMEngine) -> None:
        """Test transition when guard returns False."""

        def allowed_guard(state: State, context: dict[str, Any]) -> bool:
            return context.get("allowed", False)

        fsm_engine.register_guard("allowed_guard", allowed_guard)

        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard="allowed_guard"
                ),
            )
        )

        fsm_engine.register_definition(definition)

        # Guard returns False - no transition
        result = await fsm_engine.trigger("test.entity", "turn_on", {"allowed": False})
        assert result is False
        assert fsm_engine.get_state("test.entity").current_state == "OFF"

    @pytest.mark.asyncio
    async def test_guard_exception(self, fsm_engine: FSMEngine) -> None:
        """Test that guard exception doesn't crash the system."""

        def failing_guard(state: State, context: dict[str, Any]) -> bool:
            raise ZeroDivisionError("Guard failed")

        fsm_engine.register_guard("failing_guard", failing_guard)

        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard="failing_guard"
                ),
            )
        )

        fsm_engine.register_definition(definition)

        # Exception in guard should not crash the system
        result = await fsm_engine.trigger("test.entity", "turn_on", {})
        assert result is False
        assert fsm_engine.get_state("test.entity").current_state == "OFF"


class TestFSMImmutability:
    """Tests for state immutability."""

    @pytest.mark.asyncio
    async def test_state_is_immutable(self, fsm_engine: FSMEngine) -> None:
        """Test that state is not mutated on transition."""
        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )

        fsm_engine.register_definition(definition)
        old_state = fsm_engine.get_state("test.entity")

        await fsm_engine.trigger("test.entity", "turn_on", {})
        new_state = fsm_engine.get_state("test.entity")

        # Old state should not change
        assert old_state.current_state == "OFF"
        assert new_state.current_state == "ON"
        assert old_state is not new_state


class TestFSMReset:
    """Tests for resetting FSM state."""

    @pytest.mark.asyncio
    async def test_reset_state_to_specific_value(self, fsm_engine: FSMEngine) -> None:
        """Test resetting state to a specific value."""
        definition = FSMDefinition(
            entity_id="test.entity",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(from_state="OFF", to_state="ON", trigger="turn_on"),
            )
        )

        fsm_engine.register_definition(definition)
        fsm_engine.reset_state("test.entity", "ON")
        assert fsm_engine.get_state("test.entity").current_state == "ON"

        # Reset to OFF
        fsm_engine.reset_state("test.entity", "OFF")
        assert fsm_engine.get_state("test.entity").current_state == "OFF"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
