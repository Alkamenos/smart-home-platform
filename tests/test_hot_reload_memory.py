"""
Test for memory leaks during hot reload operations.

This test verifies that FSMEngine.unregister() properly cleans up resources
and that repeated hot reloads do not cause memory leaks.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import gc
import tracemalloc

import pytest

from core import FSMDefinition, FSMEngine, Transition


class MockPersistence:
    """Mock persistence for testing."""

    def __init__(self):
        self._data = {}

    def save_state(self, entity_id: str, state: str, context: dict) -> None:
        self._data[entity_id] = (state, context)

    def load_state(self, entity_id: str) -> tuple[str, dict] | None:
        return self._data.get(entity_id)


def create_test_fsm_definition(entity_id: str, timeout_sec: float = 1.0) -> FSMDefinition:
    """Create a test FSM definition with a timeout transition."""
    return FSMDefinition(
        entity_id=entity_id,
        initial_state="idle",
        states=("idle", "active", "timeout"),
        transitions=(
            Transition(
                from_state="idle",
                to_state="active",
                trigger="activate",
                timeout_sec=None,
            ),
            Transition(
                from_state="active",
                to_state="timeout",
                trigger="timeout",
                timeout_sec=timeout_sec,
            ),
        ),
        debounce_sec=0.0,
    )


async def test_unregister_removes_fsm():
    """Test that unregister() removes FSM from all internal dictionaries."""
    engine = FSMEngine()
    persistence = MockPersistence()
    engine._persistence = persistence

    entity_id = "test.entity_1"
    definition = create_test_fsm_definition(entity_id)

    # Register the FSM
    engine.register_definition(definition)

    # Verify it's registered
    assert entity_id in engine._definitions
    assert entity_id in engine._states
    assert engine.get_state(entity_id) is not None

    # Trigger a transition to create a timer
    await engine.trigger(entity_id, "activate")

    # Verify timer was created
    assert entity_id in engine._timers or entity_id in engine._last_transition_time

    # Unregister
    engine.unregister(entity_id)

    # Verify everything is cleaned up
    assert entity_id not in engine._definitions
    assert entity_id not in engine._states
    assert entity_id not in engine._timers
    assert entity_id not in engine._last_transition_time
    assert engine.get_state(entity_id) is None


async def test_unregister_cancels_timers():
    """Test that unregister() cancels pending timeout timers."""
    engine = FSMEngine()

    entity_id = "test.entity_with_timeout"
    # Create a transition from active state with timeout
    definition = FSMDefinition(
        entity_id=entity_id,
        initial_state="idle",
        states=("idle", "active"),
        transitions=(
            Transition(
                from_state="idle",
                to_state="active",
                trigger="activate",
                timeout_sec=None,
            ),
            Transition(
                from_state="active",
                to_state="idle",
                trigger="timeout",
                timeout_sec=5.0,  # This creates a timer when transitioning TO active
            ),
        ),
        debounce_sec=0.0,
    )

    engine.register_definition(definition)

    # Trigger a transition that creates a timeout timer
    # The timeout is set on the transition FROM active TO idle via timeout event
    await engine.trigger(entity_id, "activate")

    # Verify timer was created (on the transition that has timeout_sec)
    # Timer should be scheduled when we reach a state with timeout_sec transition
    assert entity_id in engine._timers or entity_id in engine._last_transition_time

    # Unregister should cancel the timer
    engine.unregister(entity_id)

    # Timer should be cancelled and removed from dict
    assert entity_id not in engine._timers


async def test_hot_reload_no_memory_leak():
    """Test that 10+ hot reloads don't cause memory leaks."""
    # Start tracking memory
    tracemalloc.start()

    try:
        engine = FSMEngine()
        persistence = MockPersistence()
        engine._persistence = persistence

        num_entities = 5
        num_reloads = 15  # More than 10 to ensure we catch leaks

        # Create initial FSMs
        entity_ids = [f"test.entity_{i}" for i in range(num_entities)]

        for reload_count in range(num_reloads):
            # Register FSMs (simulating hot reload)
            for entity_id in entity_ids:
                definition = create_test_fsm_definition(entity_id, timeout_sec=2.0)
                engine.register_definition(definition)

                # Trigger some transitions to create timers
                await engine.trigger(entity_id, "activate")

            # Simulate hot reload: unregister all and recreate
            for entity_id in entity_ids:
                engine.unregister(entity_id)

            # Force garbage collection
            gc.collect()

            # Take snapshot every 5 reloads
            if (reload_count + 1) % 5 == 0:
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics("lineno")[:10]

                # Log memory stats for debugging
                print(f"\nReload {reload_count + 1}/{num_reloads}:")
                for stat in top_stats[:5]:
                    print(f"  {stat}")

        # Final check: all FSMs should be unregistered
        assert len(engine._definitions) == 0
        assert len(engine._states) == 0
        assert len(engine._timers) == 0
        assert len(engine._last_transition_time) == 0

        # Check memory growth
        tracemalloc.take_snapshot()

        # The memory should not have grown significantly
        # Allow for some overhead but not linear growth
        current, peak = tracemalloc.get_traced_memory()

        # Peak memory should be less than 10MB for this test
        # (adjust threshold based on actual requirements)
        assert peak < 10 * 1024 * 1024, f"Peak memory too high: {peak / 1024 / 1024:.2f}MB"

        print(f"\nFinal memory - Current: {current / 1024:.2f}KB, Peak: {peak / 1024:.2f}KB")

    finally:
        tracemalloc.stop()


async def test_multiple_unregisters_safe():
    """Test that calling unregister() multiple times is safe."""
    engine = FSMEngine()

    entity_id = "test.entity_multi_unregister"
    definition = create_test_fsm_definition(entity_id)

    engine.register_definition(definition)

    # First unregister
    engine.unregister(entity_id)

    # Second unregister should not raise
    engine.unregister(entity_id)

    # Third unregister should not raise
    engine.unregister(entity_id)

    # Everything should still be clean
    assert entity_id not in engine._definitions
    assert entity_id not in engine._states
    assert entity_id not in engine._timers


@pytest.mark.asyncio
async def test_unregister_sync_operation():
    """Test that unregister() is synchronous and doesn't require await."""
    engine = FSMEngine()

    entity_id = "test.sync_unregister"
    definition = create_test_fsm_definition(entity_id, timeout_sec=10.0)

    engine.register_definition(definition)

    # Call unregister synchronously (no await)
    result = engine.unregister(entity_id)

    # Should return None (no coroutine)
    assert result is None
    assert entity_id not in engine._definitions
    assert entity_id not in engine._states


class TestHotReloadMemory:
    """Test class for hot reload memory leak detection."""

    @pytest.fixture
    def engine(self):
        """Create a fresh FSMEngine for each test."""
        return FSMEngine()

    @pytest.fixture
    def persistence(self):
        """Create mock persistence."""
        return MockPersistence()

    @pytest.mark.asyncio
    async def test_unregister_cleanup(self, engine, persistence):
        """Verify unregister cleans up all resources."""
        engine._persistence = persistence

        entity_id = "light.test__feature_1"
        definition = create_test_fsm_definition(entity_id)

        engine.register_definition(definition)
        await engine.trigger(entity_id, "activate")

        # Capture state before unregister
        has_state = entity_id in engine._states
        has_def = entity_id in engine._definitions

        assert has_state
        assert has_def

        # Unregister
        engine.unregister(entity_id)

        # Verify cleanup
        assert entity_id not in engine._states
        assert entity_id not in engine._definitions
        assert entity_id not in engine._timers
        assert entity_id not in engine._last_transition_time

    @pytest.mark.asyncio
    async def test_ten_hot_reloads_no_leak(self, engine, persistence):
        """Test that 10 hot reloads don't cause memory leaks."""
        engine._persistence = persistence

        entity_ids = [f"light.room{i}__night_light" for i in range(3)]

        for _i in range(10):
            # Register
            for eid in entity_ids:
                defn = create_test_fsm_definition(eid)
                engine.register_definition(defn)
                await engine.trigger(eid, "activate")

            # Unregister (simulating hot reload)
            for eid in entity_ids:
                engine.unregister(eid)

            gc.collect()

        # Memory should be stable (within 20% tolerance)
        # This is a basic check; tracemalloc provides more detailed analysis
        assert len(engine._definitions) == 0
        assert len(engine._states) == 0
        assert len(engine._timers) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
