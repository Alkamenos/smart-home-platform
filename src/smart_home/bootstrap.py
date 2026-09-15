"""
Bootstrap module for Smart Home Platform.

This module provides the bootstrap_platform() function that initializes
all platform components and wires them together correctly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from smart_home.adapters.ha_adapter import HAAdapter
from smart_home.core.command_dispatcher import CommandDispatcher
from smart_home.core.control_tracker import ControlTracker
from smart_home.core.event_bus import EventBus
from smart_home.core.event_router import EventRouter
from smart_home.core.fsm import FSMEngine
from smart_home.core.middleware import ManualLockoutMiddleware
from smart_home.core.models.manifest import Manifest, load_manifest


@dataclass
class PlatformContext:
    """
    Container for all platform components.

    Attributes:
        manifest: Loaded manifest with automation rules.
        event_bus: EventBus for publishing/subscribing to events.
        fsm: FSMEngine for state machine management.
        control_tracker: ControlTracker for tracking manual interventions.
        adapter: HAAdapter or MockAdapter for calling services.
        dispatcher: CommandDispatcher with middleware chain.
        event_router: EventRouter for routing sensor events to FSMs.
    """

    manifest: Manifest
    event_bus: EventBus
    fsm: FSMEngine
    control_tracker: ControlTracker
    adapter: Any  # HAAdapter or MockAdapter
    dispatcher: CommandDispatcher
    event_router: EventRouter


def bootstrap_platform(manifest_path: str) -> PlatformContext:
    """
    Bootstrap the smart home platform with all components.

    This function:
    1. Loads the manifest via load_manifest()
    2. Creates EventBus
    3. Creates FSMEngine
    4. Creates ControlTracker (if not already created)
    5. Creates EventRouter
    6. Creates HAAdapter with EventRouter
    7. Creates CommandDispatcher with empty middleware list
    8. Creates ManualLockoutMiddleware with automation_rules and ControlTracker
    9. Adds middleware to dispatcher via add_middleware()
    10. Returns PlatformContext with all components

    Args:
        manifest_path: Path to the manifest YAML file.

    Returns:
        PlatformContext containing all initialized components.

    Example:
        >>> from smart_home.bootstrap import bootstrap_platform
        >>> ctx = bootstrap_platform("instances/leonids_house/manifest.yaml")
        >>> # Now ctx.dispatcher has ManualLockoutMiddleware
    """
    # 1. Load manifest
    manifest = load_manifest(manifest_path)

    # 2. Create EventBus
    event_bus = EventBus()

    # 3. Create FSMEngine (without dispatcher initially)
    fsm = FSMEngine()

    # 4. Create ControlTracker
    control_tracker = ControlTracker(history_size=100)

    # 5. Create EventRouter
    event_router = EventRouter(manifest=manifest, engine=fsm)

    # 6. Create HAAdapter with EventRouter
    ws_url = os.environ.get("HA_WEBSOCKET_URL", "ws://localhost:8123/api/websocket")
    ha_token = os.environ.get("HA_TOKEN")

    adapter = HAAdapter(
        mode="websocket",
        engine=fsm,
        event_router=event_router,
        ws_url=ws_url,
        token=ha_token,
    )

    # 7. Create CommandDispatcher with empty middleware list
    dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[])

    # 8. Create ManualLockoutMiddleware with automation_rules and ControlTracker
    middleware = ManualLockoutMiddleware(
        automation_rules=manifest.automation_rules,
        control_tracker=control_tracker,
    )

    # 9. Add middleware to dispatcher
    dispatcher.add_middleware(middleware)

    # Link adapter to FSM engine for event forwarding
    adapter.set_fsm_engine(fsm)

    # 10. Return PlatformContext with all components
    return PlatformContext(
        manifest=manifest,
        event_bus=event_bus,
        fsm=fsm,
        control_tracker=control_tracker,
        adapter=adapter,
        dispatcher=dispatcher,
        event_router=event_router,
    )


if __name__ == "__main__":
    # Example usage
    import sys

    manifest_path = sys.argv[1] if len(sys.argv) > 1 else "instances/leonids_house/manifest.yaml"

    ctx = bootstrap_platform(manifest_path)
    print("Platform bootstrapped successfully!")
    print(f"  Instance: {ctx.manifest.instance.name}")
    print(f"  Devices: {len(ctx.manifest.devices)}")
    print(f"  Zones: {len(ctx.manifest.zones)}")
    print(f"  Lighting lockout: {ctx.manifest.automation_rules.lighting.manual_lockout_min} min")
    print(f"  Climate lockout: {ctx.manifest.automation_rules.climate.manual_lockout_min} min")
    print(
        f"  Ventilation lockout: {ctx.manifest.automation_rules.ventilation.manual_lockout_min} min"
    )
    print(f"  Global lockout: {ctx.manifest.automation_rules.global_manual_lockout_min} min")
