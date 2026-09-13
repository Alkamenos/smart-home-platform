"""
Middleware Layer for Smart Home Platform.

This module provides a middleware system for applying global rules from automation_rules
to all commands from all behaviors automatically.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger

from .command_dispatcher import CommandIntent
from .models.manifest import AutomationRules

# Import ControlTracker from core package
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.control_tracker import ControlTracker, TriggerSource


class Middleware(ABC):
    """
    Base class for middleware in the command processing pipeline.
    
    Middleware classes can intercept, modify, or block CommandIntent objects
    before they are processed by the CommandDispatcher.
    
    Subclasses must implement the process method to define their behavior.
    """
    
    @abstractmethod
    async def process(self, intent: CommandIntent) -> Optional[CommandIntent]:
        """
        Process a command intent.
        
        Args:
            intent: The CommandIntent to process.
        
        Returns:
            The processed CommandIntent if it should continue through the chain,
            or None if the command should be blocked.
        """
        pass


class ManualLockoutMiddleware(Middleware):
    """
    Middleware that enforces manual lockout rules from automation_rules.
    
    This middleware uses ControlTracker to check if a device was manually
    controlled within the last manual_lockout_min minutes. If so, it blocks
    automated commands to prevent conflicts with manual user control.
    
    Attributes:
        _automation_rules: The automation rules from the manifest.
        _control_tracker: ControlTracker instance for tracking manual interventions.
    """
    
    def __init__(self, automation_rules: AutomationRules, control_tracker: ControlTracker) -> None:
        """
        Initialize ManualLockoutMiddleware.
        
        Args:
            automation_rules: AutomationRules instance from the manifest.
            control_tracker: ControlTracker instance for tracking manual control events.
        """
        self._automation_rules = automation_rules
        self._control_tracker = control_tracker
    
    def _get_lockout_minutes(self, domain: str) -> int:
        """
        Get the lockout duration in minutes for a given domain.
        
        First checks for a global lockout setting, then falls back to
        domain-specific settings.
        
        Args:
            domain: The device domain (e.g., "light", "climate", "ventilation").
        
        Returns:
            The lockout duration in minutes, or 0 if not configured.
        """
        # First check global lockout setting
        global_lockout = getattr(self._automation_rules, 'global_manual_lockout_min', 0)
        if global_lockout > 0:
            return global_lockout
        
        # Fall back to domain-specific settings
        if domain == "light":
            return self._automation_rules.lighting.manual_lockout_min
        elif domain == "climate" or domain == "thermostat":
            return self._automation_rules.climate.manual_lockout_min
        elif domain == "fan" or domain == "ventilation":
            return self._automation_rules.ventilation.manual_lockout_min
        else:
            # Default to lighting rules for unknown domains
            return self._automation_rules.lighting.manual_lockout_min
    
    def _is_manual_source(self, source: str) -> bool:
        """
        Check if a command source is considered manual user control.
        
        Args:
            source: The source name of the command.
        
        Returns:
            True if the source represents manual control, False otherwise.
        """
        manual_sources = {"manual", "user", "home_assistant", "voice", "alexa", "google"}
        return source.lower() in manual_sources
    
    def record_manual_control(self, device_id: str) -> None:
        """
        Record that a device was manually controlled using ControlTracker.
        
        This should be called when a manual control command is detected
        to start the lockout period.
        
        Args:
            device_id: The ID of the device that was manually controlled.
        """
        self._control_tracker.record(device_id, TriggerSource.MANUAL, "manual_control")
        logger.info(f"Recorded manual control for device {device_id} via ControlTracker")
    
    def _is_in_lockout_period(self, device_id: str, domain: str) -> bool:
        """
        Check if a device is currently in a manual lockout period.
        
        Uses ControlTracker to determine if there was a manual intervention
        within the lockout period.
        
        Args:
            device_id: The ID of the device to check.
            domain: The device domain for determining lockout duration.
        
        Returns:
            True if the device is in lockout period, False otherwise.
        """
        lockout_minutes = self._get_lockout_minutes(domain)
        
        if lockout_minutes <= 0:
            return False
        
        # Use ControlTracker to check for recent manual intervention
        return self._control_tracker.was_manual_within(device_id, lockout_minutes)
    
    async def process(self, intent: CommandIntent) -> Optional[CommandIntent]:
        """
        Process a command intent, blocking automated commands during manual lockout.
        
        If the device was manually controlled within the lockout period and
        the incoming command is from an automated source (not manual), the
        command is blocked.
        
        Args:
            intent: The CommandIntent to process.
        
        Returns:
            The intent if it should be processed, None if it should be blocked.
        """
        device_id = intent.device_id
        domain = intent.domain
        source = intent.source.lower()
        
        # Check if this is a manual control command - record it and allow
        if self._is_manual_source(source):
            self.record_manual_control(device_id)
            return intent
        
        # Check if we're in a lockout period for automated commands
        if self._is_in_lockout_period(device_id, domain):
            last_manual = self._control_tracker.get_last_manual(device_id)
            lockout_minutes = self._get_lockout_minutes(domain)
            logger.info(
                f"Blocked automated command from {source} for {device_id}: "
                f"manual lockout active (last manual control at {last_manual.timestamp if last_manual else 'unknown'}, "
                f"lockout duration: {lockout_minutes} min)"
            )
            return None
        
        # Allow the command
        return intent


if __name__ == "__main__":
    pass
