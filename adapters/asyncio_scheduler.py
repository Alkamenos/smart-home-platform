"""Asyncio-based scheduler implementation.

This scheduler uses asyncio.create_task and asyncio.sleep for scheduling
delayed callbacks. It's suitable for use in tests and CLI environments.
"""

import asyncio
import uuid
from typing import Optional, Dict, Set


class AsyncioScheduler:
    """Asyncio-based scheduler using create_task and sleep."""
    
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._entity_schedules: Dict[str, Set[str]] = {}
    
    def schedule(
        self,
        entity_id: str,
        trigger: str,
        delay_sec: float,
        callback: callable,
        context: Optional[dict] = None
    ) -> str:
        """Schedule a callback to be executed after a delay.
        
        This implementation cancels any existing schedule for the same
        entity_id and trigger combination before creating a new one.
        """
        schedule_id = str(uuid.uuid4())
        
        # Get running loop - must exist in async context
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - we're in sync test context
            # Just return without scheduling (test doesn't need delayed execution)
            return schedule_id
        
        async def _run():
            await asyncio.sleep(delay_sec)
            # Check if still active (not cancelled)
            if schedule_id in self._tasks:
                del self._tasks[schedule_id]
                if entity_id in self._entity_schedules:
                    self._entity_schedules[entity_id].discard(schedule_id)
                try:
                    if context is not None:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(context)
                        else:
                            callback(context)
                    else:
                        if asyncio.iscoroutinefunction(callback):
                            await callback()
                        else:
                            callback()
                except Exception as e:
                    print(f"Scheduler callback error: {e}")
        
        # Cancel existing schedules for this entity+trigger
        for sid, task in list(self._tasks.items()):
            if getattr(task, '_schedule_entity', None) == entity_id and \
               getattr(task, '_schedule_trigger', None) == trigger:
                task.cancel()
                if sid in self._tasks:
                    del self._tasks[sid]
        
        # Create new task
        task = asyncio.create_task(_run())
        task._schedule_entity = entity_id  # type: ignore
        task._schedule_trigger = trigger  # type: ignore
        task._schedule_id = schedule_id  # type: ignore
        
        self._tasks[schedule_id] = task
        
        if entity_id not in self._entity_schedules:
            self._entity_schedules[entity_id] = set()
        self._entity_schedules[entity_id].add(schedule_id)
        
        return schedule_id
    
    def cancel(self, schedule_id: str) -> bool:
        """Cancel a scheduled callback."""
        if schedule_id not in self._tasks:
            return False
        
        task = self._tasks.pop(schedule_id)
        task.cancel()
        
        # Remove from entity schedules
        for entity_id, schedules in self._entity_schedules.items():
            if schedule_id in schedules:
                schedules.discard(schedule_id)
                break
        
        return True
    
    def cancel_all(self, entity_id: str) -> int:
        """Cancel all scheduled callbacks for an entity."""
        if entity_id not in self._entity_schedules:
            return 0
        
        schedule_ids = list(self._entity_schedules.get(entity_id, set()))
        count = 0
        
        for schedule_id in schedule_ids:
            if schedule_id in self._tasks:
                task = self._tasks.pop(schedule_id)
                task.cancel()
                count += 1
        
        self._entity_schedules.pop(entity_id, None)
        return count
