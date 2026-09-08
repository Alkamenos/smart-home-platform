"""PyScript-compatible scheduler implementation for Home Assistant.

This scheduler uses PyScript's task.sleep() function instead of asyncio.sleep,
making it compatible with the PyScript environment in Home Assistant.
"""

import uuid
from typing import Optional, Dict, Set, Any

from core.scheduler import BaseScheduler


# Try to import PyScript-specific modules
# These will be available when running in PyScript environment
try:
    # PyScript provides task module
    from pyscript import task  # type: ignore
    PYSCRIPT_AVAILABLE = True
except ImportError:
    PYSCRIPT_AVAILABLE = False
    task = None  # type: ignore


class PyScriptScheduler(BaseScheduler):
    """PyScript-compatible scheduler using task.sleep().
    
    This scheduler is designed to work within the PyScript environment
    in Home Assistant, where asyncio may not be fully compatible.
    It uses PyScript's native task.sleep() for delays.
    """
    
    def __init__(self):
        self._pending_tasks: Dict[str, Any] = {}
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
        
        In PyScript, this creates a new task that sleeps for the specified
        duration and then executes the callback.
        """
        if not PYSCRIPT_AVAILABLE:
            raise RuntimeError(
                "PyScriptScheduler requires PyScript environment. "
                "Use AsyncioScheduler for tests/CLI."
            )
        
        schedule_id = str(uuid.uuid4())
        
        # Cancel existing schedules for this entity+trigger
        self._cancel_existing(entity_id, trigger)
        
        async def _run():
            try:
                await task.sleep(delay_sec)
                
                # Check if still active (not cancelled)
                if schedule_id in self._pending_tasks:
                    del self._pending_tasks[schedule_id]
                    if entity_id in self._entity_schedules:
                        self._entity_schedules[entity_id].discard(schedule_id)
                    
                    try:
                        if context is not None:
                            if hasattr(callback, '__await__'):
                                await callback(context)
                            else:
                                callback(context)
                        else:
                            if hasattr(callback, '__await__'):
                                await callback()
                            else:
                                callback()
                    except Exception as e:
                        # In PyScript, we log but don't propagate
                        print(f"PyScriptScheduler callback error: {e}")
                        
            except Exception as e:
                print(f"PyScriptScheduler task error: {e}")
        
        # Create the task using PyScript's task mechanism
        task_obj = task.create_task(_run())
        task_obj._schedule_entity = entity_id
        task_obj._schedule_trigger = trigger
        task_obj._schedule_id = schedule_id
        
        self._pending_tasks[schedule_id] = task_obj
        
        if entity_id not in self._entity_schedules:
            self._entity_schedules[entity_id] = set()
        self._entity_schedules[entity_id].add(schedule_id)
        
        return schedule_id
    
    def cancel(self, schedule_id: str) -> bool:
        """Cancel a scheduled callback."""
        if schedule_id not in self._pending_tasks:
            return False
        
        task_obj = self._pending_tasks.pop(schedule_id)
        
        # In PyScript, we can cancel tasks
        try:
            task_obj.cancel()
        except Exception:
            pass
        
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
            if schedule_id in self._pending_tasks:
                task_obj = self._pending_tasks.pop(schedule_id)
                try:
                    task_obj.cancel()
                except Exception:
                    pass
                count += 1
        
        self._entity_schedules.pop(entity_id, None)
        return count
    
    def _cancel_existing(self, entity_id: str, trigger: str) -> None:
        """Cancel existing schedules for the same entity+trigger."""
        to_cancel = []
        
        for schedule_id, task_obj in self._pending_tasks.items():
            if (getattr(task_obj, '_schedule_entity', None) == entity_id and
                getattr(task_obj, '_schedule_trigger', None) == trigger):
                to_cancel.append(schedule_id)
        
        for schedule_id in to_cancel:
            self.cancel(schedule_id)
