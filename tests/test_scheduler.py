"""Unit tests for the Scheduler module."""

import asyncio
import pytest
from src.smart_home.core.scheduler import Scheduler


@pytest.mark.asyncio
async def test_cancel_prevents_callback_execution():
    """Test that cancel() guarantees old timers are cancelled and don't fire."""
    scheduler = Scheduler()
    callback_fired = False
    entity_id = "test_entity"

    async def callback(entity_id, trigger, ctx):
        nonlocal callback_fired
        callback_fired = True

    # Schedule a task with a long delay
    scheduled_task = scheduler.schedule(
        entity_id=entity_id,
        trigger="test_trigger",
        delay=10.0,  # 10 seconds delay
        ctx={"data": "test"},
        callback=callback,
    )

    # Verify task is active
    assert scheduled_task.is_active()
    assert scheduler.has_active_tasks(entity_id)

    # Cancel the task immediately
    cancelled_count = scheduler.cancel(entity_id)
    assert cancelled_count == 1

    # Verify task is no longer active
    assert not scheduled_task.is_active()
    assert not scheduler.has_active_tasks(entity_id)

    # Wait enough time for the original delay to pass
    await asyncio.sleep(0.5)

    # Verify callback never fired
    assert callback_fired is False


@pytest.mark.asyncio
async def test_cancel_multiple_tasks_for_same_entity():
    """Test that cancel() cancels all tasks for an entity."""
    scheduler = Scheduler()
    fired_callbacks = []
    entity_id = "test_entity"

    async def callback_maker(idx):
        async def callback(entity_id, trigger, ctx):
            fired_callbacks.append(idx)
        return callback

    # Schedule multiple tasks for the same entity
    tasks = []
    for i in range(5):
        cb = await callback_maker(i)
        task = scheduler.schedule(
            entity_id=entity_id,
            trigger=f"trigger_{i}",
            delay=10.0,
            ctx={"index": i},
            callback=cb,
        )
        tasks.append(task)

    # Verify all tasks are active
    for task in tasks:
        assert task.is_active()
    
    assert len(scheduler.get_active_tasks(entity_id)) == 5

    # Cancel all tasks for this entity
    cancelled_count = scheduler.cancel(entity_id)
    assert cancelled_count == 5

    # Verify no tasks are active
    for task in tasks:
        assert not task.is_active()
    
    assert len(scheduler.get_active_tasks(entity_id)) == 0

    # Wait and verify no callbacks fired
    await asyncio.sleep(0.5)
    assert len(fired_callbacks) == 0


@pytest.mark.asyncio
async def test_cancel_does_not_affect_other_entities():
    """Test that cancel() only affects the specified entity."""
    scheduler = Scheduler()
    fired_callbacks = []
    entity_a = "entity_a"
    entity_b = "entity_b"

    async def callback_maker(entity_name):
        async def callback(entity_id, trigger, ctx):
            fired_callbacks.append(entity_name)
        return callback

    # Schedule tasks for different entities
    cb_a = await callback_maker("a")
    cb_b = await callback_maker("b")
    
    task_a = scheduler.schedule(
        entity_id=entity_a,
        trigger="trigger_a",
        delay=0.1,  # Short delay so it fires
        ctx={},
        callback=cb_a,
    )
    
    task_b = scheduler.schedule(
        entity_id=entity_b,
        trigger="trigger_b",
        delay=10.0,  # Long delay
        ctx={},
        callback=cb_b,
    )

    # Cancel only entity_a's tasks
    cancelled_count = scheduler.cancel(entity_a)
    assert cancelled_count == 1

    # Wait for entity_a's task delay
    await asyncio.sleep(0.2)

    # entity_a's callback should NOT have fired (was cancelled)
    # entity_b's task should still be active
    assert "a" not in fired_callbacks
    assert task_b.is_active()
    assert scheduler.has_active_tasks(entity_b)


@pytest.mark.asyncio
async def test_cancel_returns_zero_for_nonexistent_entity():
    """Test that cancel() returns 0 when entity has no tasks."""
    scheduler = Scheduler()
    
    cancelled_count = scheduler.cancel("nonexistent_entity")
    assert cancelled_count == 0


@pytest.mark.asyncio
async def test_cancel_all_graceful_shutdown():
    """Test that cancel_all() cancels all tasks for graceful shutdown."""
    scheduler = Scheduler()
    fired_callbacks = []

    async def callback_maker(idx):
        async def callback(entity_id, trigger, ctx):
            fired_callbacks.append(idx)
        return callback

    # Schedule tasks for multiple entities
    for i in range(10):
        cb = await callback_maker(i)
        entity_id = f"entity_{i}"
        scheduler.schedule(
            entity_id=entity_id,
            trigger=f"trigger_{i}",
            delay=10.0,
            ctx={"index": i},
            callback=cb,
        )

    # Cancel all tasks
    total_cancelled = scheduler.cancel_all()
    assert total_cancelled == 10

    # Verify no tasks remain
    for i in range(10):
        assert not scheduler.has_active_tasks(f"entity_{i}")

    # Wait and verify no callbacks fired
    await asyncio.sleep(0.5)
    assert len(fired_callbacks) == 0


@pytest.mark.asyncio
async def test_task_completes_if_not_cancelled():
    """Test that a task completes normally if not cancelled."""
    scheduler = Scheduler()
    callback_fired = False
    callback_ctx = None

    async def callback(entity_id, trigger, ctx):
        nonlocal callback_fired, callback_ctx
        callback_fired = True
        callback_ctx = ctx

    # Schedule a task with short delay
    scheduler.schedule(
        entity_id="test_entity",
        trigger="test_trigger",
        delay=0.1,
        ctx={"key": "value"},
        callback=callback,
    )

    # Wait for the task to complete
    await asyncio.sleep(0.2)

    # Verify callback fired with correct context
    assert callback_fired is True
    assert callback_ctx == {"key": "value"}
    
    # Verify no active tasks remain
    assert not scheduler.has_active_tasks("test_entity")


@pytest.mark.asyncio
async def test_cancel_immediately_after_schedule():
    """Test cancelling a task immediately after scheduling."""
    scheduler = Scheduler()
    callback_fired = False

    async def callback(entity_id, trigger, ctx):
        nonlocal callback_fired
        callback_fired = True

    # Schedule and immediately cancel
    task = scheduler.schedule(
        entity_id="test_entity",
        trigger="test_trigger",
        delay=5.0,
        ctx={},
        callback=callback,
    )
    
    # Cancel before any sleep
    scheduler.cancel("test_entity")
    
    # Task should be marked as done/cancelled
    assert task.task.done() or not task.is_active()
    
    # Wait and verify callback didn't fire
    await asyncio.sleep(0.3)
    assert callback_fired is False


@pytest.mark.asyncio
async def test_scheduler_cleanup_after_task_completion():
    """Test that completed tasks are cleaned up from the scheduler."""
    scheduler = Scheduler()

    async def callback(entity_id, trigger, ctx):
        pass

    # Schedule a task with short delay
    scheduler.schedule(
        entity_id="test_entity",
        trigger="test_trigger",
        delay=0.05,
        ctx={},
        callback=callback,
    )

    # Task should be active
    assert scheduler.has_active_tasks("test_entity")

    # Wait for completion
    await asyncio.sleep(0.15)

    # Task should be cleaned up automatically
    assert not scheduler.has_active_tasks("test_entity")
