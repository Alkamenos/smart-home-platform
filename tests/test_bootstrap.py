"""
Tests for bootstrap_platform() function.

Tests cover:
1. PlatformContext contains all required components
2. ManualLockoutMiddleware is added to dispatcher
3. Manifest is loaded correctly
4. All components are properly wired together
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from bootstrap import PlatformContext, bootstrap_platform
from core import ManualLockoutMiddleware


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "instances" / "leonids_house" / "manifest.yaml"


class TestBootstrapPlatform:
    """Tests for bootstrap_platform() function."""

    def test_bootstrap_returns_platform_context(self):
        """Test that bootstrap_platform returns a PlatformContext."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert isinstance(ctx, PlatformContext)

    def test_platform_context_contains_manifest(self):
        """Test that PlatformContext contains manifest."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert ctx.manifest is not None
        assert ctx.manifest.instance.id == "leonids_house"
        assert ctx.manifest.instance.name == "Leonid's House"

    def test_platform_context_contains_event_bus(self):
        """Test that PlatformContext contains EventBus."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert ctx.event_bus is not None
        from core.event_bus import EventBus

        assert isinstance(ctx.event_bus, EventBus)

    def test_platform_context_contains_fsm_engine(self):
        """Test that PlatformContext contains FSMEngine."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert ctx.fsm is not None
        from core import FSMEngine

        assert isinstance(ctx.fsm, FSMEngine)

    def test_platform_context_contains_control_tracker(self):
        """Test that PlatformContext contains ControlTracker."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert ctx.control_tracker is not None
        from core.control_tracker import ControlTracker

        assert isinstance(ctx.control_tracker, ControlTracker)

    def test_platform_context_contains_adapter(self):
        """Test that PlatformContext contains MockAdapter."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert ctx.adapter is not None
        from adapters.mock_adapter import MockAdapter

        assert isinstance(ctx.adapter, MockAdapter)

    def test_platform_context_contains_dispatcher(self):
        """Test that PlatformContext contains CommandDispatcher."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert ctx.dispatcher is not None
        from core import CommandDispatcher

        assert isinstance(ctx.dispatcher, CommandDispatcher)

    def test_manual_lockout_middleware_added_to_dispatcher(self):
        """Test that ManualLockoutMiddleware is added to dispatcher."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        # Check that dispatcher has middleware
        assert len(ctx.dispatcher._middlewares) == 1

        # Check that the middleware is ManualLockoutMiddleware
        middleware = ctx.dispatcher._middlewares[0]
        assert isinstance(middleware, ManualLockoutMiddleware)

    def test_middleware_has_automation_rules_from_manifest(self):
        """Test that middleware has automation_rules from manifest."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        middleware = ctx.dispatcher._middlewares[0]

        # Check that middleware has automation_rules
        assert middleware._automation_rules is not None

        # Verify rules match manifest
        assert middleware._automation_rules.lighting.manual_lockout_min == 60
        assert middleware._automation_rules.climate.manual_lockout_min == 30
        assert middleware._automation_rules.ventilation.manual_lockout_min == 15
        assert middleware._automation_rules.global_manual_lockout_min == 60

    def test_middleware_has_control_tracker(self):
        """Test that middleware has ControlTracker."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        middleware = ctx.dispatcher._middlewares[0]

        # Check that middleware has control_tracker
        assert middleware._control_tracker is not None

        # Verify it's the same instance as in context
        assert middleware._control_tracker is ctx.control_tracker

    def test_adapter_linked_to_fsm_engine(self):
        """Test that adapter is linked to FSM engine."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        # Check that adapter has fsm_engine set
        assert ctx.adapter._fsm_engine is ctx.fsm

    def test_manifest_devices_loaded(self):
        """Test that manifest devices are loaded correctly."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert len(ctx.manifest.devices) == 6

        device_ids = [d.id for d in ctx.manifest.devices]
        assert "light.kitchen" in device_ids
        assert "light.living_room" in device_ids
        assert "light.bedroom" in device_ids
        assert "climate.kitchen" in device_ids
        assert "climate.living_room" in device_ids
        assert "fan.bathroom" in device_ids

    def test_manifest_zones_loaded(self):
        """Test that manifest zones are loaded correctly."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        assert len(ctx.manifest.zones) == 4

        zone_ids = [z.id for z in ctx.manifest.zones]
        assert "kitchen" in zone_ids
        assert "living_room" in zone_ids
        assert "bedroom" in zone_ids
        assert "bathroom" in zone_ids

    @pytest.mark.asyncio
    async def test_dispatcher_with_middleware_blocks_automated_commands(self):
        """Test that dispatcher with middleware blocks automated commands during lockout."""
        ctx = bootstrap_platform(str(MANIFEST_PATH))

        from core import CommandIntent

        # First, send a manual command to start lockout
        manual_intent = CommandIntent(
            device_id="light.test_device",
            domain="light",
            service="turn_on",
            data={},
            priority=50,
            source="manual",
        )

        result = await ctx.dispatcher.submit(manual_intent)

        # Manual command should be accepted
        assert result is True

        # Verify manual control was recorded
        last_manual = ctx.control_tracker.get_last_manual("light.test_device")
        assert last_manual is not None

        # Now try an automated command
        auto_intent = CommandIntent(
            device_id="light.test_device",
            domain="light",
            service="turn_off",
            data={},
            priority=10,
            source="motion_lighting",
        )

        result = await ctx.dispatcher.submit(auto_intent)

        # Automated command should be blocked by middleware
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
