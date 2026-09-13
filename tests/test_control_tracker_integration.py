"""
Integration tests for ControlTracker and ManualLockoutMiddleware.

Tests cover:
1. Emulating manual device turn-on
2. Checking that automated commands are blocked for manual_lockout_min minutes
3. Checking that after timeout expires, commands work again
4. Verifying lockout works for all behaviors without code in each
"""

import pytest
import time
from unittest.mock import patch, AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core'))

from src.smart_home.core.middleware import ManualLockoutMiddleware
from src.smart_home.core.command_dispatcher import CommandIntent, CommandDispatcher
from src.smart_home.core.models.manifest import (
    AutomationRules, LightingAutomation, ClimateAutomation, VentilationAutomation
)
from core.control_tracker import ControlTracker, TriggerSource


@pytest.fixture
def control_tracker():
    """Create ControlTracker instance."""
    return ControlTracker(history_size=100)


@pytest.fixture
def automation_rules_with_global_lockout():
    """Create automation rules with global manual_lockout setting."""
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
        global_manual_lockout_min=5,  # Global 5 minute lockout for testing
    )


@pytest.fixture
def middleware_with_global(automation_rules_with_global_lockout, control_tracker):
    """Create ManualLockoutMiddleware instance with global lockout."""
    return ManualLockoutMiddleware(
        automation_rules=automation_rules_with_global_lockout,
        control_tracker=control_tracker
    )


class TestControlTrackerIntegration:
    """Integration tests for ControlTracker with ManualLockoutMiddleware."""
    
    @pytest.mark.asyncio
    async def test_manual_turnon_blocks_automation(self, middleware_with_global):
        """
        Test that manual turn-on of a device blocks automated commands.
        
        This test emulates a user manually turning on a light, then verifies
        that an automated command (e.g., from motion sensor) is blocked.
        """
        tracker = middleware_with_global._control_tracker
        
        # Emulate manual turn-on of a device
        manual_intent = CommandIntent(
            device_id="light.kitchen",
            domain="light",
            service="turn_on",
            data={"brightness": 255},
            priority=50,
            source="manual",
        )
        
        result = await middleware_with_global.process(manual_intent)
        
        # Manual command should be allowed
        assert result is not None
        
        # Verify it was recorded in ControlTracker
        last_manual = tracker.get_last_manual("light.kitchen")
        assert last_manual is not None
        assert last_manual.source == TriggerSource.MANUAL
        
        # Now try an automated command (e.g., from motion lighting behavior)
        auto_intent = CommandIntent(
            device_id="light.kitchen",
            domain="light",
            service="turn_off",
            data={},
            priority=10,
            source="motion_lighting",
        )
        
        result = await middleware_with_global.process(auto_intent)
        
        # Automated command should be blocked during lockout period
        assert result is None
    
    @pytest.mark.asyncio
    async def test_commands_work_after_timeout_expires(self, middleware_with_global):
        """
        Test that automated commands work again after lockout timeout expires.
        
        This test verifies that after manual_lockout_min minutes have passed,
        automated commands are no longer blocked.
        """
        tracker = middleware_with_global._control_tracker
        base_time = [time.time()]  # Use list to allow mutation in closure
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            # First, manual turn-on
            manual_intent = CommandIntent(
                device_id="light.bedroom",
                domain="light",
                service="turn_on",
                data={},
                priority=50,
                source="user",
            )
            await middleware_with_global.process(manual_intent)
            
            # Verify lockout is active immediately
            auto_intent = CommandIntent(
                device_id="light.bedroom",
                domain="light",
                service="turn_off",
                data={},
                priority=10,
                source="schedule",
            )
            result = await middleware_with_global.process(auto_intent)
            assert result is None, "Should be blocked immediately after manual control"
            
            # Move time forward past the global lockout period (5 min + 1 sec)
            base_time[0] = base_time[0] + (5 * 60) + 1
            
            # Now try the same automated command
            result = await middleware_with_global.process(auto_intent)
            
            # Should be allowed after timeout expires
            assert result is not None
    
    @pytest.mark.asyncio
    async def test_lockout_works_for_all_behaviors(self, middleware_with_global):
        """
        Test that lockout works for all behaviors without code in each.
        
        This test verifies that the middleware applies to all types of
        automated sources (behaviors), demonstrating that no per-behavior
        code is needed.
        """
        tracker = middleware_with_global._control_tracker
        base_time = [time.time()]  # Use list to allow mutation in closure
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            # Manual control first
            manual_intent = CommandIntent(
                device_id="fan.bathroom",
                domain="fan",
                service="turn_on",
                data={},
                priority=50,
                source="home_assistant",
            )
            await middleware_with_global.process(manual_intent)
            
            # List of different behavior sources that should all be blocked
            behavior_sources = [
                "humidity_control",      # Ventilation humidity behavior
                "night_light",           # Night light behavior
                "motion_lighting",       # Motion-based lighting behavior
                "eco_mode",              # Climate eco mode behavior
                "schedule",              # Schedule-based behavior
                "timeout_cancellation",  # Timeout cancellation behavior
            ]
            
            for source in behavior_sources:
                auto_intent = CommandIntent(
                    device_id="fan.bathroom",
                    domain="fan",
                    service="turn_off",
                    data={},
                    priority=10,
                    source=source,
                )
                
                result = await middleware_with_global.process(auto_intent)
                
                # All automated behaviors should be blocked during lockout
                assert result is None, f"Behavior '{source}' should be blocked during lockout"
    
    @pytest.mark.asyncio
    async def test_global_lockout_takes_precedence_over_domain_specific(
        self, automation_rules_with_global_lockout, control_tracker
    ):
        """
        Test that global_manual_lockout_min takes precedence over domain-specific settings.
        
        When global_manual_lockout_min > 0, it should be used instead of
        domain-specific manual_lockout_min values.
        """
        middleware = ManualLockoutMiddleware(
            automation_rules=automation_rules_with_global_lockout,
            control_tracker=control_tracker
        )
        
        # Global lockout is 5 minutes, but lighting has 60 minutes
        # The global should take precedence
        lockout_minutes = middleware._get_lockout_minutes("light")
        assert lockout_minutes == 5, "Global lockout should override domain-specific"
        
        # Same for climate (30 min domain-specific)
        lockout_minutes = middleware._get_lockout_minutes("climate")
        assert lockout_minutes == 5, "Global lockout should override domain-specific"
        
        # Same for ventilation (15 min domain-specific)
        lockout_minutes = middleware._get_lockout_minutes("ventilation")
        assert lockout_minutes == 5, "Global lockout should override domain-specific"
    
    @pytest.mark.asyncio
    async def test_domain_specific_used_when_global_is_zero(self, control_tracker):
        """
        Test that domain-specific lockout is used when global is 0 or not set.
        """
        automation_rules = AutomationRules(
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
            global_manual_lockout_min=0,  # Disabled - use domain-specific
        )
        
        middleware = ManualLockoutMiddleware(
            automation_rules=automation_rules,
            control_tracker=control_tracker
        )
        
        # Should use domain-specific values
        assert middleware._get_lockout_minutes("light") == 60
        assert middleware._get_lockout_minutes("climate") == 30
        assert middleware._get_lockout_minutes("ventilation") == 15
        assert middleware._get_lockout_minutes("fan") == 15  # fan maps to ventilation
    
    @pytest.mark.asyncio
    async def test_full_integration_with_mock_ha_adapter(self, control_tracker):
        """
        Full integration test with CommandDispatcher and mock HA adapter.
        
        This test demonstrates the complete flow from manual control through
        the middleware to the HA adapter.
        """
        automation_rules = AutomationRules(
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
            global_manual_lockout_min=2,  # 2 minutes for testing
        )
        
        middleware = ManualLockoutMiddleware(
            automation_rules=automation_rules,
            control_tracker=control_tracker
        )
        
        # Mock HA adapter
        mock_adapter = AsyncMock()
        mock_adapter.call_service = AsyncMock(return_value=True)
        
        # Create dispatcher with middleware
        dispatcher = CommandDispatcher(
            ha_adapter=mock_adapter,
            middlewares=[middleware]
        )
        
        base_time = [time.time()]  # Use list to allow mutation in closure
        
        def mock_time():
            return base_time[0]
        
        with patch('core.control_tracker.time.time', mock_time):
            # Manual command - should go through
            manual_intent = CommandIntent(
                device_id="light.living_room",
                domain="light",
                service="turn_on",
                data={},
                priority=50,
                source="manual",
            )
            result = await dispatcher.submit(manual_intent)
            assert result is True, "Manual command should succeed"
            mock_adapter.call_service.assert_called()
            mock_adapter.call_service.reset_mock()
            
            # Automated command during lockout - should be blocked
            auto_intent = CommandIntent(
                device_id="light.living_room",
                domain="light",
                service="turn_off",
                data={},
                priority=10,
                source="motion_lighting",
            )
            result = await dispatcher.submit(auto_intent)
            assert result is False, "Automated command should be blocked during lockout"
            mock_adapter.call_service.assert_not_called()
            
            # After lockout expires - should succeed
            base_time[0] = base_time[0] + (2 * 60) + 1  # 2 min + 1 sec
            
            result = await dispatcher.submit(auto_intent)
            assert result is True, "Automated command should succeed after lockout"
            mock_adapter.call_service.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
