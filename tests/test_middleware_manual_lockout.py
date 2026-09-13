"""
Unit tests for Middleware module.

Tests cover:
1. ManualLockoutMiddleware blocks automated commands during lockout period.
2. Manual commands are always allowed and start the lockout period.
3. Commands after lockout period expires are allowed.
4. Different domains use different lockout durations from automation_rules.
5. Uses ControlTracker for tracking manual interventions.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import time

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core'))

from src.smart_home.core.middleware import Middleware, ManualLockoutMiddleware
from src.smart_home.core.command_dispatcher import CommandIntent
from src.smart_home.core.models.manifest import AutomationRules, LightingAutomation, ClimateAutomation, VentilationAutomation
from core.control_tracker import ControlTracker, TriggerSource


@pytest.fixture
def control_tracker():
    """Create ControlTracker instance."""
    return ControlTracker(history_size=100)


@pytest.fixture
def automation_rules():
    """Create automation rules with manual_lockout settings."""
    return AutomationRules(
        lighting=LightingAutomation(
            motion_enabled=True,
            schedule_enabled=True,
            manual_lockout_min=60,
        ),
        climate=ClimateAutomation(
            safety_lockout_enabled=True,
            away_mode_enabled=True,
            manual_lockout_min=30,
        ),
        ventilation=VentilationAutomation(
            humidity_based=True,
            manual_lockout_min=15,
        ),
        global_manual_lockout_min=0,  # Default: use domain-specific settings
    )


@pytest.fixture
def middleware(automation_rules, control_tracker):
    """Create ManualLockoutMiddleware instance."""
    return ManualLockoutMiddleware(automation_rules=automation_rules, control_tracker=control_tracker)


class TestManualLockoutMiddleware:
    """Tests for ManualLockoutMiddleware."""
    
    @pytest.mark.asyncio
    async def test_manual_command_allowed_and_starts_lockout(self, middleware):
        """
        Test that manual commands are always allowed and start the lockout period.
        """
        intent = CommandIntent(
            device_id="light.kitchen",
            domain="light",
            service="turn_on",
            data={},
            priority=50,
            source="manual",
        )
        
        result = await middleware.process(intent)
        
        # Manual command should be allowed
        assert result is not None
        assert result.device_id == "light.kitchen"
        
        # Verify that manual control was recorded in ControlTracker
        last_manual = middleware._control_tracker.get_last_manual("light.kitchen")
        assert last_manual is not None
        assert last_manual.source == TriggerSource.MANUAL
    
    @pytest.mark.asyncio
    async def test_automated_command_blocked_during_lockout(self, middleware):
        """
        Test that automated commands are blocked during manual lockout period.
        """
        # First, send a manual command to start lockout
        manual_intent = CommandIntent(
            device_id="light.bedroom",
            domain="light",
            service="turn_on",
            data={},
            priority=50,
            source="manual",
        )
        await middleware.process(manual_intent)
        
        # Now try an automated command
        auto_intent = CommandIntent(
            device_id="light.bedroom",
            domain="light",
            service="turn_off",
            data={},
            priority=10,
            source="motion_lighting",
        )
        
        result = await middleware.process(auto_intent)
        
        # Automated command should be blocked
        assert result is None
    
    @pytest.mark.asyncio
    async def test_automated_command_allowed_after_lockout_expires(self, middleware, monkeypatch):
        """
        Test that automated commands are allowed after lockout period expires.
        """
        # Since we use ControlTracker which uses time.time(), we need to mock time
        base_time = time.time()
        
        def mock_time():
            return base_time
        
        with patch('core.control_tracker.time.time', mock_time):
            # First, send a manual command
            manual_intent = CommandIntent(
                device_id="light.living_room",
                domain="light",
                service="turn_on",
                data={},
                priority=50,
                source="user",
            )
            await middleware.process(manual_intent)
            
            # Move time forward past the lockout period (60 minutes + 1 minute)
            nonlocal base_time
            base_time = base_time + 61 * 60  # 61 minutes in seconds
            
            # Now try an automated command
            auto_intent = CommandIntent(
                device_id="light.living_room",
                domain="light",
                service="turn_off",
                data={},
                priority=10,
                source="motion_lighting",
            )
            
            result = await middleware.process(auto_intent)
            
            # Automated command should be allowed after lockout expires
            assert result is not None
    
    @pytest.mark.asyncio
    async def test_different_domains_use_correct_lockout_duration(self, automation_rules, monkeypatch):
        """
        Test that different domains use their respective lockout durations.
        """
        control_tracker = ControlTracker(history_size=100)
        middleware = ManualLockoutMiddleware(automation_rules=automation_rules, control_tracker=control_tracker)
        
        base_time = time.time()
        
        def mock_time():
            return base_time
        
        with patch('core.control_tracker.time.time', mock_time):
            # Test climate domain (30 min lockout)
            climate_manual = CommandIntent(
                device_id="climate.thermostat",
                domain="climate",
                service="set_temperature",
                data={"temperature": 22},
                priority=50,
                source="manual",
            )
            await middleware.process(climate_manual)
            
            # Move time forward 15 minutes (still within climate lockout of 30 min)
            nonlocal base_time
            base_time = base_time + 15 * 60  # 15 minutes in seconds
            
            climate_auto = CommandIntent(
                device_id="climate.thermostat",
                domain="climate",
                service="set_temperature",
                data={"temperature": 20},
                priority=10,
                source="eco_mode",
            )
            result = await middleware.process(climate_auto)
            
            # Should still be blocked (15 min < 30 min lockout)
            assert result is None
            
            # Move time forward past climate lockout (30 + 1 = 31 min total)
            base_time = base_time + 16 * 60  # 16 more minutes
            
            result = await middleware.process(climate_auto)
            
            # Should now be allowed
            assert result is not None
    
    @pytest.mark.asyncio
    async def test_ventilation_domain_lockout(self, automation_rules, monkeypatch):
        """
        Test ventilation domain uses its specific lockout duration (15 min).
        """
        control_tracker = ControlTracker(history_size=100)
        middleware = ManualLockoutMiddleware(automation_rules=automation_rules, control_tracker=control_tracker)
        
        base_time = time.time()
        
        def mock_time():
            return base_time
        
        with patch('core.control_tracker.time.time', mock_time):
            # Manual control of ventilation
            vent_manual = CommandIntent(
                device_id="fan.bathroom",
                domain="fan",
                service="turn_on",
                data={},
                priority=50,
                source="home_assistant",
            )
            await middleware.process(vent_manual)
            
            # Move time forward 10 minutes (within 15 min lockout)
            nonlocal base_time
            base_time = base_time + 10 * 60  # 10 minutes in seconds
            
            vent_auto = CommandIntent(
                device_id="fan.bathroom",
                domain="fan",
                service="turn_off",
                data={},
                priority=10,
                source="humidity_control",
            )
            result = await middleware.process(vent_auto)
            
            # Should be blocked
            assert result is None
            
            # Move time forward past 15 min lockout
            base_time = base_time + 6 * 60  # 6 more minutes
            
            result = await middleware.process(vent_auto)
            
            # Should be allowed
            assert result is not None
    
    @pytest.mark.asyncio
    async def test_different_devices_independent(self, middleware):
        """
        Test that lockout is per-device, not global.
        """
        # Manual control of light.kitchen
        manual_kitchen = CommandIntent(
            device_id="light.kitchen",
            domain="light",
            service="turn_on",
            data={},
            priority=50,
            source="manual",
        )
        await middleware.process(manual_kitchen)
        
        # Automated command for light.bedroom (different device)
        auto_bedroom = CommandIntent(
            device_id="light.bedroom",
            domain="light",
            service="turn_on",
            data={},
            priority=10,
            source="motion_lighting",
        )
        
        result = await middleware.process(auto_bedroom)
        
        # Should be allowed since bedroom wasn't manually controlled
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_various_manual_sources_recognized(self, middleware):
        """
        Test that various manual source names are recognized.
        """
        manual_sources = ["manual", "user", "home_assistant", "voice", "alexa", "google"]
        
        for i, source in enumerate(manual_sources):
            device_id = f"light.device_{i}"
            intent = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_on",
                data={},
                priority=50,
                source=source,
            )
            
            result = await middleware.process(intent)
            
            # All manual sources should be allowed
            assert result is not None
            # Verify it was recorded in ControlTracker
            last_manual = middleware._control_tracker.get_last_manual(device_id)
            assert last_manual is not None
    
    @pytest.mark.asyncio
    async def test_automated_sources_blocked(self, middleware):
        """
        Test that automated sources are subject to lockout.
        """
        # First establish manual lockout
        manual_intent = CommandIntent(
            device_id="light.test",
            domain="light",
            service="turn_on",
            data={},
            priority=50,
            source="manual",
        )
        await middleware.process(manual_intent)
        
        # Various automated sources
        auto_sources = ["motion_lighting", "night_light", "eco_mode", "schedule", "automation"]
        
        for source in auto_sources:
            auto_intent = CommandIntent(
                device_id="light.test",
                domain="light",
                service="turn_off",
                data={},
                priority=10,
                source=source,
            )
            
            result = await middleware.process(auto_intent)
            
            # All automated sources should be blocked during lockout
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
