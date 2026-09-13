"""
End-to-End test for ManualLockoutMiddleware.

This test demonstrates the full middleware workflow:
1. Load test manifest with automation_rules.lighting.manual_lockout_min: 60
2. Create platform via bootstrap_platform()
3. Emulate manual device control (source="manual")
4. Verify ControlTracker recorded the event
5. Emulate automated command (source="lighting", priority=10)
6. Verify command is BLOCKED by middleware
7. Emulate 60 minutes passing (via freezegun)
8. Emulate automated command again
9. Verify command now PASSES

Scenario:
t=0:00 - Manual light on (source="manual")
t=0:01 - Automation tries to turn on (source="lighting") -> BLOCKED
t=1:00 - Lockout period expires
t=1:01 - Automation tries to turn on -> PASSES
"""

import pytest
import sys
import os
import time
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from freezegun import freeze_time
from src.smart_home.bootstrap import bootstrap_platform
from src.smart_home.core.command_dispatcher import CommandIntent


class TestManualLockoutE2E:
    """End-to-End tests for ManualLockoutMiddleware."""
    
    @pytest.mark.asyncio
    async def test_manual_lockout_blocks_automation_then_allows_after_expiry(self):
        """
        Full scenario test:
        t=0:00 - Manual light on
        t=0:01 - Automation blocked
        t=1:00 - Lockout expires
        t=1:01 - Automation passes
        """
        # Use a base time that we can manipulate
        base_time = [time.time()]
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            # Bootstrap platform (must be inside patch so ControlTracker uses mocked time)
            ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
            
            device_id = "light.test_e2e"
            
            # ===== t=0:00 - Manual control =====
            manual_intent = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_on",
                data={"brightness": 255},
                priority=50,
                source="manual",
            )
            
            result = await ctx.dispatcher.submit(manual_intent)
            
            # Manual command should be accepted
            assert result is True, "Manual command should be accepted"
            
            # Verify ControlTracker recorded the event
            last_manual = ctx.control_tracker.get_last_manual(device_id)
            assert last_manual is not None, "ControlTracker should record manual control"
            assert last_manual.source == "manual"
            
            # ===== t=0:01 - Automation tries (should be BLOCKED) =====
            # Move time forward 1 minute
            base_time[0] += 60  # 1 minute in seconds
            
            auto_intent_1 = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_on",
                data={"brightness": 128},
                priority=10,
                source="lighting",
            )
            
            result = await ctx.dispatcher.submit(auto_intent_1)
            
            # Automated command should be BLOCKED during lockout
            assert result is False, "Automated command should be BLOCKED during lockout period"
            
            # ===== t=1:00 - Lockout period expires =====
            # Move time forward 59 more minutes (total 60 minutes from manual control)
            base_time[0] += 59 * 60  # 59 minutes in seconds
            
            # ===== t=1:01 - Automation tries again (should PASS) =====
            base_time[0] += 60  # 1 more minute
            
            auto_intent_2 = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_off",
                data={},
                priority=10,
                source="lighting",
            )
            
            result = await ctx.dispatcher.submit(auto_intent_2)
            
            # Automated command should now PASS after lockout expires
            assert result is True, "Automated command should PASS after lockout expires"
    
    @pytest.mark.asyncio
    async def test_multiple_manual_controls_reset_lockout_timer(self):
        """
        Test that multiple manual controls reset the lockout timer.
        
        Scenario:
        t=0:00 - Manual control
        t=0:30 - Another manual control (resets timer)
        t=1:00 - Automation tries (should still be BLOCKED, only 30 min since last manual)
        t=1:30 - Automation tries (should PASS, 60 min since last manual)
        """
        base_time = [time.time()]
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
            
            device_id = "light.test_reset"
            
            # t=0:00 - First manual control
            manual_1 = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_on",
                data={},
                priority=50,
                source="manual",
            )
            await ctx.dispatcher.submit(manual_1)
            
            # t=0:30 - Second manual control (resets timer)
            base_time[0] += 30 * 60  # 30 minutes
            
            manual_2 = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_off",
                data={},
                priority=50,
                source="user",
            )
            await ctx.dispatcher.submit(manual_2)
            
            # t=1:00 - Automation tries (30 min since last manual, should be BLOCKED)
            base_time[0] += 30 * 60  # 30 more minutes
            
            auto_1 = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_on",
                data={},
                priority=10,
                source="motion_lighting",
            )
            result = await ctx.dispatcher.submit(auto_1)
            assert result is False, "Should be BLOCKED (only 30 min since last manual)"
            
            # t=1:30 - Automation tries (60 min since last manual, should PASS)
            base_time[0] += 30 * 60  # 30 more minutes
            
            auto_2 = CommandIntent(
                device_id=device_id,
                domain="light",
                service="turn_on",
                data={},
                priority=10,
                source="motion_lighting",
            )
            result = await ctx.dispatcher.submit(auto_2)
            assert result is True, "Should PASS (60 min since last manual)"
    
    @pytest.mark.asyncio
    async def test_different_devices_independent_lockout(self):
        """
        Test that lockout is per-device, not global.
        
        Scenario:
        t=0:00 - Manual control of light.kitchen
        t=0:01 - Automation for light.bedroom should PASS (different device)
        """
        base_time = [time.time()]
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
            
            # Manual control of kitchen
            manual_kitchen = CommandIntent(
                device_id="light.kitchen",
                domain="light",
                service="turn_on",
                data={},
                priority=50,
                source="manual",
            )
            await ctx.dispatcher.submit(manual_kitchen)
            
            # Verify kitchen has manual lockout
            assert ctx.control_tracker.get_last_manual("light.kitchen") is not None
            
            # Move time forward 1 minute
            base_time[0] += 60  # 1 minute
            
            # Automation for bedroom (different device) should PASS
            auto_bedroom = CommandIntent(
                device_id="light.bedroom",
                domain="light",
                service="turn_on",
                data={},
                priority=10,
                source="motion_lighting",
            )
            result = await ctx.dispatcher.submit(auto_bedroom)
            
            assert result is True, "Automation for different device should PASS"
    
    @pytest.mark.asyncio
    async def test_global_lockout_setting_applies(self):
        """
        Test that global_manual_lockout_min setting applies to all domains.
        
        The test manifest has global_manual_lockout_min: 60, which should
        override domain-specific settings.
        """
        base_time = [time.time()]
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
            
            # Manual control of climate device
            manual_climate = CommandIntent(
                device_id="climate.thermostat",
                domain="climate",
                service="set_temperature",
                data={"temperature": 22},
                priority=50,
                source="manual",
            )
            await ctx.dispatcher.submit(manual_climate)
            
            # t=0:01 - Automation tries (should be BLOCKED by global 60 min setting)
            base_time[0] += 60  # 1 minute
            
            auto_climate = CommandIntent(
                device_id="climate.thermostat",
                domain="climate",
                service="set_temperature",
                data={"temperature": 20},
                priority=10,
                source="eco_mode",
            )
            result = await ctx.dispatcher.submit(auto_climate)
            
            # Should be BLOCKED (global lockout is 60 min)
            assert result is False, "Climate automation should be BLOCKED by global lockout"
            
            # t=31:00 - Try again (would pass with domain-specific 30 min, but global is 60)
            base_time[0] += 30 * 60  # 30 minutes
            
            result = await ctx.dispatcher.submit(auto_climate)
            assert result is False, "Still BLOCKED (global 60 min > domain 30 min)"
            
            # t=61:00 - Try again (should PASS now)
            base_time[0] += 30 * 60  # 30 more minutes
            
            result = await ctx.dispatcher.submit(auto_climate)
            assert result is True, "Should PASS after global lockout expires"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
