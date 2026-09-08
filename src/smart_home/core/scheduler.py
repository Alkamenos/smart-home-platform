"""Async scheduler module for smart home core."""

import asyncio
from collections.abc import Callable
from typing import Any


class ScheduledTask:
    """Represents a scheduled task."""
    
    def __init__(self, trigger: str, delay: float, ctx: dict[str, Any] | None = None) -> None:
        self.trigger = trigger
        self.delay = delay
        self.ctx = ctx or {}
        self.task: asyncio.Task | None = None
    
    def is_active(self) -> bool:
        """Check if the task is still active (not cancelled or done)."""
        if self.task is None:
            return False
        # Task is active only if it's not done and not being cancelled
        if self.task.done():
            return False
        # cancelling() available Python 3.11+
        try:
            return not self.task.cancelling()
        except AttributeError:
            # Fallback for Python < 3.11
            return True
    
    def __hash__(self) -> int:
        return id(self)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScheduledTask):
            return NotImplemented
        return id(self) == id(other)


class Scheduler:
    """Async scheduler based on asyncio.create_task and asyncio.sleep.
    
    Stores tasks in dict[entity_id, set[ScheduledTask]].
    """

    def __init__(self) -> None:
        self._tasks: dict[str, set[ScheduledTask]] = {}

    async def _run_task(
        self,
        entity_id: str,
        scheduled_task: ScheduledTask,
        callback: Callable | None = None,
    ) -> None:
        """Internal method to run a scheduled task after delay."""
        try:
            await asyncio.sleep(scheduled_task.delay)
            if callback and scheduled_task.is_active():
                await callback(entity_id, scheduled_task.trigger, scheduled_task.ctx)
        except asyncio.CancelledError:
            # Task was cancelled, silently exit
            raise
        finally:
            # Clean up from the set when done
            if entity_id in self._tasks:
                self._tasks[entity_id].discard(scheduled_task)

    def schedule(
        self,
        entity_id: str,
        trigger: str,
        delay: float,
        ctx: dict[str, Any] | None = None,
        callback: Callable | None = None,
    ) -> ScheduledTask:
        """Schedule a task for an entity.
        
        Args:
            entity_id: ID of the entity to schedule the task for.
            trigger: Trigger type/name for the task.
            delay: Delay in seconds before executing the task.
            ctx: Context data for the task.
            callback: Optional callback to execute after delay.
            
        Returns:
            The created ScheduledTask object.
        """
        if entity_id not in self._tasks:
            self._tasks[entity_id] = set()
        
        scheduled_task = ScheduledTask(
            trigger=trigger,
            delay=delay,
            ctx=ctx or {},
        )
        
        # Create the async task
        scheduled_task.task = asyncio.create_task(
            self._run_task(entity_id, scheduled_task, callback)
        )
        
        self._tasks[entity_id].add(scheduled_task)
        
        return scheduled_task

    def cancel(self, entity_id: str) -> int:
        """Cancel all active tasks for an entity.
        
        Args:
            entity_id: ID of the entity whose tasks should be cancelled.
            
        Returns:
            Number of tasks that were cancelled.
        """
        if entity_id not in self._tasks:
            return 0
        
        # Get and clear the set atomically
        tasks_to_cancel = self._tasks.pop(entity_id, set())
        
        cancelled_count = 0
        for scheduled_task in tasks_to_cancel:
            if scheduled_task.is_active():
                scheduled_task.task.cancel()
                cancelled_count += 1
        
        return cancelled_count

    def cancel_all(self) -> int:
        """Cancel all active tasks for graceful shutdown.
        
        Returns:
            Total number of tasks that were cancelled.
        """
        total_cancelled = 0
        
        entity_ids = list(self._tasks.keys())
        for entity_id in entity_ids:
            total_cancelled += self.cancel(entity_id)
        
        return total_cancelled

    def get_active_tasks(self, entity_id: str) -> list[ScheduledTask]:
        """Get all active tasks for an entity.
        
        Args:
            entity_id: ID of the entity.
            
        Returns:
            List of active ScheduledTask objects.
        """
        if entity_id not in self._tasks:
            return []
        
        return [t for t in self._tasks[entity_id] if t.is_active()]

    def has_active_tasks(self, entity_id: str) -> bool:
        """Check if an entity has any active tasks.
        
        Args:
            entity_id: ID of the entity.
            
        Returns:
            True if there are active tasks, False otherwise.
        """
        return len(self.get_active_tasks(entity_id)) > 0
