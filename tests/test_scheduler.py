"""Tests for scheduler abstraction.

This module tests the BaseScheduler interface and AsyncioScheduler implementation.
"""

import pytest
import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scheduler import BaseScheduler
from adapters.asyncio_scheduler import AsyncioScheduler


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestAsyncioScheduler:
    """Tests for AsyncioScheduler implementation."""
    
    @pytest.mark.asyncio
    async def test_schedule_triggers_callback_after_delay(self):
        """Test that callback is executed after the specified delay."""
        scheduler = AsyncioScheduler()
        callback_called = False
        callback_context = None
        
        async def callback(ctx=None):
            nonlocal callback_called, callback_context
            callback_called = True
            callback_context = ctx
        
        schedule_id = scheduler.schedule(
            entity_id="light.test",
            trigger="timeout",
            delay_sec=0.1,
            callback=callback,
            context={"test": "value"}
        )
        
        assert schedule_id is not None
        assert not callback_called
        
        # Wait for the callback to be executed
        await asyncio.sleep(0.15)
        
        assert callback_called
        assert callback_context == {"test": "value"}
    
    @pytest.mark.asyncio
    async def test_cancel_prevents_callback_execution(self):
        """Test that cancelling a schedule prevents callback execution."""
        scheduler = AsyncioScheduler()
        callback_called = False
        
        async def callback(ctx=None):
            nonlocal callback_called
            callback_called = True
        
        schedule_id = scheduler.schedule(
            entity_id="light.test",
            trigger="timeout",
            delay_sec=0.5,
            callback=callback
        )
        
        # Cancel immediately
        cancelled = scheduler.cancel(schedule_id)
        assert cancelled
        
        # Wait longer than the delay
        await asyncio.sleep(0.6)
        
        # Callback should not have been called
        assert not callback_called
    
    @pytest.mark.asyncio
    async def test_cancel_all_for_entity(self):
        """Test cancelling all schedules for an entity."""
        scheduler = AsyncioScheduler()
        callback1_called = False
        callback2_called = False
        
        async def callback1(ctx=None):
            nonlocal callback1_called
            callback1_called = True
        
        async def callback2(ctx=None):
            nonlocal callback2_called
            callback2_called = True
        
        # Schedule two timers for the same entity
        scheduler.schedule(
            entity_id="light.test",
            trigger="timeout1",
            delay_sec=0.1,
            callback=callback1
        )
        
        scheduler.schedule(
            entity_id="light.test",
            trigger="timeout2",
            delay_sec=0.1,
            callback=callback2
        )
        
        # Cancel all for this entity
        cancelled_count = scheduler.cancel_all("light.test")
        assert cancelled_count == 2
        
        # Wait for potential callbacks
        await asyncio.sleep(0.2)
        
        # Neither callback should have been called
        assert not callback1_called
        assert not callback2_called
    
    @pytest.mark.asyncio
    async def test_schedule_cancels_previous_same_trigger(self):
        """Test that scheduling a new timer with same entity+trigger cancels the previous one."""
        scheduler = AsyncioScheduler()
        callback1_called = False
        callback2_called = False
        
        async def callback1(ctx=None):
            nonlocal callback1_called
            callback1_called = True
        
        async def callback2(ctx=None):
            nonlocal callback2_called
            callback2_called = True
        
        # First schedule with long delay
        scheduler.schedule(
            entity_id="light.test",
            trigger="timeout",
            delay_sec=1.0,
            callback=callback1
        )
        
        # Second schedule with short delay (should cancel the first)
        scheduler.schedule(
            entity_id="light.test",
            trigger="timeout",
            delay_sec=0.1,
            callback=callback2
        )
        
        # Wait for the second callback
        await asyncio.sleep(0.15)
        
        # Only the second callback should have been called
        assert not callback1_called
        assert callback2_called
    
    @pytest.mark.asyncio
    async def test_multiple_entities_independent(self):
        """Test that schedules for different entities are independent."""
        scheduler = AsyncioScheduler()
        entity1_called = False
        entity2_called = False
        
        async def callback1(ctx=None):
            nonlocal entity1_called
            entity1_called = True
        
        async def callback2(ctx=None):
            nonlocal entity2_called
            entity2_called = True
        
        # Schedule for entity1 with short delay
        scheduler.schedule(
            entity_id="light.entity1",
            trigger="timeout",
            delay_sec=0.1,
            callback=callback1
        )
        
        # Schedule for entity2 with longer delay
        scheduler.schedule(
            entity_id="light.entity2",
            trigger="timeout",
            delay_sec=0.3,
            callback=callback2
        )
        
        # Wait for entity1's callback
        await asyncio.sleep(0.15)
        
        assert entity1_called
        assert not entity2_called
        
        # Wait for entity2's callback
        await asyncio.sleep(0.2)
        
        assert entity2_called


class TestBaseSchedulerInterface:
    """Tests to ensure BaseScheduler interface is properly defined."""
    
    def test_base_scheduler_is_abstract(self):
        """Test that BaseScheduler cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseScheduler()
    
    def test_asyncio_scheduler_implements_interface(self):
        """Test that AsyncioScheduler implements all required methods."""
        scheduler = AsyncioScheduler()
        
        # Check all required methods exist
        assert hasattr(scheduler, 'schedule')
        assert hasattr(scheduler, 'cancel')
        assert hasattr(scheduler, 'cancel_all')
        
        # Check they are callable
        assert callable(scheduler.schedule)
        assert callable(scheduler.cancel)
        assert callable(scheduler.cancel_all)
