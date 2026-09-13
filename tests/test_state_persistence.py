#!/usr/bin/env python3
"""
Test for FSM State Persistence.

This test verifies that:
1. FSM states are saved to a JSON file after each transition.
2. On platform restart, FSMs restore their saved states instead of initial_state.
3. Invalid saved states fall back to initial_state.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_home.core.state_persistence import StatePersistence
from smart_home.core.fsm import FSMEngine, FSMDefinition, Transition, State


def test_save_and_load_state():
    """Test basic save and load functionality."""
    print("\n=== Test 1: Basic save and load ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        persistence = StatePersistence(str(storage_path))
        
        # Save a state
        persistence.save_state("light.kitchen", "active", {"brightness": 50})
        
        # Load it back
        result = persistence.load_state("light.kitchen")
        assert result is not None, "Failed to load saved state"
        state, context = result
        assert state == "active", f"Expected 'active', got '{state}'"
        assert context == {"brightness": 50}, f"Context mismatch: {context}"
        
        print("✓ State saved and loaded correctly")
        return True


def test_fsm_with_persistence():
    """Test FSM engine with persistence enabled."""
    print("\n=== Test 2: FSM with persistence ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        persistence = StatePersistence(str(storage_path))
        
        # Create FSM engine with persistence
        engine = FSMEngine(persistence=persistence)
        
        # Define a simple FSM
        definition = FSMDefinition(
            entity_id="light.test",
            initial_state="idle",
            states=("idle", "active", "standby"),
            transitions=(
                Transition(
                    from_state="idle",
                    to_state="active",
                    trigger="motion_detected"
                ),
                Transition(
                    from_state="active",
                    to_state="standby",
                    trigger="timeout"
                ),
            )
        )
        
        # Register the FSM
        engine.register_definition(definition)
        
        # Verify initial state
        state = engine.get_state("light.test")
        assert state is not None, "State should not be None"
        assert state.current_state == "idle", f"Expected 'idle', got '{state.current_state}'"
        
        # Trigger a transition
        asyncio.run(engine.trigger("light.test", "motion_detected", {}))
        
        # Verify state changed to active
        state = engine.get_state("light.test")
        assert state.current_state == "active", f"Expected 'active', got '{state.current_state}'"
        
        # Verify state was persisted
        saved = persistence.load_state("light.test")
        assert saved is not None, "State should be persisted"
        saved_state, saved_context = saved
        assert saved_state == "active", f"Expected 'active' in persistence, got '{saved_state}'"
        
        print("✓ FSM transition persisted correctly")
        return True


def test_state_restoration_on_restart():
    """Test that FSM restores saved state on 'restart'."""
    print("\n=== Test 3: State restoration on restart ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        
        # First "session": Create FSM, transition to active, persist
        persistence1 = StatePersistence(str(storage_path))
        engine1 = FSMEngine(persistence=persistence1)
        
        definition = FSMDefinition(
            entity_id="light.bedroom",
            initial_state="idle",
            states=("idle", "active"),
            transitions=(
                Transition(
                    from_state="idle",
                    to_state="active",
                    trigger="turn_on"
                ),
            )
        )
        
        engine1.register_definition(definition)
        asyncio.run(engine1.trigger("light.bedroom", "turn_on", {}))
        
        # Verify state is active
        state1 = engine1.get_state("light.bedroom")
        assert state1.current_state == "active", f"Expected 'active', got '{state1.current_state}'"
        
        # Simulate "platform restart": Create new engine with same persistence
        persistence2 = StatePersistence(str(storage_path))
        engine2 = FSMEngine(persistence=persistence2)
        
        # Register the same FSM - should restore from persistence
        engine2.register_definition(definition, restore_state=True)
        
        # Verify restored state is 'active', not 'idle'
        state2 = engine2.get_state("light.bedroom")
        assert state2 is not None, "State should not be None"
        assert state2.current_state == "active", \
            f"Expected restored state 'active', got '{state2.current_state}' (should not be 'idle')"
        
        print("✓ FSM restored to 'active' state on restart (not 'idle')")
        return True


def test_invalid_state_fallback():
    """Test that invalid saved states fall back to initial_state."""
    print("\n=== Test 4: Invalid state fallback ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        
        # Manually write an invalid state
        data = {
            "light.invalid": {
                "state": "nonexistent_state",
                "context": {}
            }
        }
        with open(storage_path, 'w') as f:
            json.dump(data, f)
        
        persistence = StatePersistence(str(storage_path))
        engine = FSMEngine(persistence=persistence)
        
        # Define FSM without 'nonexistent_state'
        definition = FSMDefinition(
            entity_id="light.invalid",
            initial_state="idle",
            states=("idle", "active"),  # 'nonexistent_state' is NOT valid
            transitions=()
        )
        
        # Register - should fall back to initial_state
        engine.register_definition(definition, restore_state=True)
        
        state = engine.get_state("light.invalid")
        assert state is not None, "State should not be None"
        assert state.current_state == "idle", \
            f"Expected fallback to 'idle', got '{state.current_state}'"
        
        print("✓ Invalid state correctly fell back to initial_state")
        return True


def test_multiple_fsms_persistence():
    """Test persistence with multiple FSMs."""
    print("\n=== Test 5: Multiple FSMs persistence ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        persistence = StatePersistence(str(storage_path))
        engine = FSMEngine(persistence=persistence)
        
        # Create multiple FSMs
        for room in ["kitchen", "bedroom", "living_room"]:
            definition = FSMDefinition(
                entity_id=f"light.{room}",
                initial_state="idle",
                states=("idle", "active"),
                transitions=(
                    Transition(
                        from_state="idle",
                        to_state="active",
                        trigger="turn_on"
                    ),
                )
            )
            engine.register_definition(definition)
        
        # Transition all to active
        for room in ["kitchen", "bedroom", "living_room"]:
            asyncio.run(engine.trigger(f"light.{room}", "turn_on", {}))
        
        # Verify all persisted
        for room in ["kitchen", "bedroom", "living_room"]:
            saved = persistence.load_state(f"light.{room}")
            assert saved is not None, f"State for light.{room} should be persisted"
            state, _ = saved
            assert state == "active", f"Expected 'active' for light.{room}"
        
        print("✓ All FSMs persisted correctly")
        return True


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 60)
    print("STATE PERSISTENCE TESTS")
    print("=" * 60)
    
    tests = [
        ("Basic save/load", test_save_and_load_state),
        ("FSM with persistence", test_fsm_with_persistence),
        ("State restoration", test_state_restoration_on_restart),
        ("Invalid state fallback", test_invalid_state_fallback),
        ("Multiple FSMs", test_multiple_fsms_persistence),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            if test_fn():
                passed += 1
        except AssertionError as e:
            print(f"✗ FAILED [{name}]: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR [{name}]: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
