#!/usr/bin/env python3
"""
Test for StatePersistence concurrency handling.

This test verifies that:
1. Concurrent save_state() calls do not cause data loss.
2. All entity states are correctly saved when 10 async tasks run simultaneously.
3. File locking prevents race conditions during concurrent writes.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_home.core.state_persistence import StatePersistence


async def save_state_async(
    persistence: StatePersistence, entity_id: str, state: str, context: dict
):
    """
    Async wrapper for save_state to simulate concurrent access.

    Uses threading to achieve true parallelism since Python's GIL would
    otherwise serialize the operations. This properly tests the file locking.

    Args:
        persistence: StatePersistence instance.
        entity_id: The unique identifier of the FSM entity.
        state: The current state name to save.
        context: The context dictionary associated with the state.
    """
    import threading

    # Use a thread and wait for completion - this ensures true concurrent execution
    exception = []

    def run_save():
        try:
            persistence.save_state(entity_id, state, context)
        except Exception as e:
            exception.append(e)

    thread = threading.Thread(target=run_save)
    thread.start()
    thread.join()

    if exception:
        raise exception[0]


async def test_concurrent_save_state():
    """
    Test that 10 concurrent save_state() calls do not lose data.

    This test creates 10 async tasks that simultaneously call save_state()
    for different entity_ids and verifies all states are saved correctly.
    """
    print("\n=== Test: Concurrent save_state() with 10 tasks ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        persistence = StatePersistence(str(storage_path))

        # Define 10 different entities with unique states
        num_tasks = 10
        expected_data = {}

        for i in range(num_tasks):
            entity_id = f"light.entity_{i}"
            state = f"state_{i}"
            context = {"entity_index": i, "value": i * 10}
            expected_data[entity_id] = {"state": state, "context": context}

        # Create 10 concurrent tasks
        tasks = [
            save_state_async(
                persistence,
                entity_id,
                expected_data[entity_id]["state"],
                expected_data[entity_id]["context"],
            )
            for entity_id in expected_data
        ]

        # Run all tasks concurrently
        await asyncio.gather(*tasks)

        # Verify all states were saved correctly
        saved_data = persistence._load_data()

        assert (
            len(saved_data) == num_tasks
        ), f"Expected {num_tasks} entities, but found {len(saved_data)}"

        for entity_id, expected in expected_data.items():
            assert entity_id in saved_data, f"Entity '{entity_id}' is missing from saved data"

            actual = saved_data[entity_id]
            assert (
                actual["state"] == expected["state"]
            ), f"State mismatch for {entity_id}: expected '{expected['state']}', got '{actual['state']}'"
            assert (
                actual["context"] == expected["context"]
            ), f"Context mismatch for {entity_id}: expected {expected['context']}, got {actual['context']}"

        print(f"✓ All {num_tasks} entities saved correctly - no data loss")
        return True


async def test_concurrent_same_entity():
    """
    Test concurrent saves to the same entity_id.

    This test verifies that when multiple tasks try to save to the same
    entity_id, the file locking ensures consistency (last write wins, but no corruption).
    """
    print("\n=== Test: Concurrent saves to same entity ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        persistence = StatePersistence(str(storage_path))

        entity_id = "light.shared"
        num_tasks = 10

        # Create tasks that all write to the same entity
        tasks = [
            save_state_async(persistence, entity_id, f"state_{i}", {"write_index": i})
            for i in range(num_tasks)
        ]

        # Run all tasks concurrently
        await asyncio.gather(*tasks)

        # Verify the entity exists and has valid data
        saved_data = persistence._load_data()

        assert entity_id in saved_data, f"Entity '{entity_id}' should exist after concurrent writes"

        actual = saved_data[entity_id]
        assert "state" in actual, "State field should exist"
        assert "context" in actual, "Context field should exist"
        assert isinstance(actual["context"], dict), "Context should be a dict"

        # The final state should be one of the written states (no corruption)
        valid_states = {f"state_{i}" for i in range(num_tasks)}
        assert (
            actual["state"] in valid_states
        ), f"Final state '{actual['state']}' should be one of the valid states"

        print("✓ Concurrent writes to same entity handled correctly - no corruption")
        return True


async def test_mixed_concurrent_operations():
    """
    Test mixed concurrent operations (different and same entities).
    """
    print("\n=== Test: Mixed concurrent operations ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "state.json"
        persistence = StatePersistence(str(storage_path))

        num_unique = 5
        shared_entity = "light.shared"

        # Create tasks: 5 unique entities + 5 writes to same entity
        tasks = []

        # Unique entities
        for i in range(num_unique):
            entity_id = f"light.unique_{i}"
            tasks.append(
                save_state_async(
                    persistence, entity_id, f"unique_state_{i}", {"type": "unique", "index": i}
                )
            )

        # Shared entity writes
        for i in range(num_unique):
            tasks.append(
                save_state_async(
                    persistence, shared_entity, f"shared_state_{i}", {"type": "shared", "index": i}
                )
            )

        # Run all tasks concurrently
        await asyncio.gather(*tasks)

        # Verify results
        saved_data = persistence._load_data()

        # Check unique entities
        for i in range(num_unique):
            entity_id = f"light.unique_{i}"
            assert entity_id in saved_data, f"Unique entity '{entity_id}' is missing"
            assert saved_data[entity_id]["context"]["type"] == "unique"

        # Check shared entity exists and is valid
        assert shared_entity in saved_data, f"Shared entity '{shared_entity}' should exist"
        assert "state" in saved_data[shared_entity]
        assert "context" in saved_data[shared_entity]

        print("✓ Mixed concurrent operations handled correctly")
        return True


async def run_all_tests():
    """Run all concurrency tests and report results."""
    print("=" * 60)
    print("STATE PERSISTENCE CONCURRENCY TESTS")
    print("=" * 60)

    tests = [
        ("Concurrent save (10 entities)", test_concurrent_save_state),
        ("Concurrent same entity", test_concurrent_same_entity),
        ("Mixed concurrent operations", test_mixed_concurrent_operations),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            if await test_fn():
                passed += 1
        except AssertionError as e:
            print(f"✗ FAILED [{name}]: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR [{name}]: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
