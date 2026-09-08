"""Scheduler abstraction for FSM Engine.

This module provides abstract base classes and implementations for scheduling
delayed triggers in the FSM engine. Different environments (asyncio, PyScript)
require different scheduling mechanisms.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseScheduler(ABC):
    """Abstract base class for scheduling delayed triggers.
    
    The scheduler is responsible for executing a callback after a specified
    delay. Implementations must support cancellation of pending schedules.
    """
    
    @abstractmethod
    def schedule(
        self,
        entity_id: str,
        trigger: str,
        delay_sec: float,
        callback: callable,
        context: Optional[dict] = None
    ) -> str:
        """Schedule a callback to be executed after a delay.
        
        Args:
            entity_id: The entity ID this schedule is for.
            trigger: The trigger name associated with this schedule.
            delay_sec: Delay in seconds before executing the callback.
            callback: The callable to execute after the delay.
            context: Optional context dictionary to pass to the callback.
            
        Returns:
            A unique schedule ID that can be used to cancel this schedule.
        """
        pass
    
    @abstractmethod
    def cancel(self, schedule_id: str) -> bool:
        """Cancel a scheduled callback.
        
        Args:
            schedule_id: The schedule ID returned by schedule().
            
        Returns:
            True if the schedule was cancelled, False if it didn't exist
            or already executed.
        """
        pass
    
    @abstractmethod
    def cancel_all(self, entity_id: str) -> int:
        """Cancel all scheduled callbacks for an entity.
        
        Args:
            entity_id: The entity ID to cancel all schedules for.
            
        Returns:
            The number of schedules cancelled.
        """
        pass
