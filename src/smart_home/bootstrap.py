"""
Bootstrap module for Smart Home Platform.

This module provides the bootstrap_platform() function that initializes
all platform components and wires them together correctly.
"""

from __future__ import annotations

from dataclasses import dataclass

from smart_home.adapters.mock_adapter import MockAdapter
from smart_home.core.command_dispatcher import CommandDispatcher
from smart_home.core.control_tracker import ControlTracker
from smart_home.core.event_bus import EventBus
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
        adapter: HAAdapter (MockAdapter for tests) for calling services.
        dispatcher: CommandDispatcher with middleware chain.
    """

    manifest: Manifest
    event_bus: EventBus
    fsm: FSMEngine
    control_tracker: ControlTracker
    adapter: MockAdapter
    dispatcher: CommandDispatcher


def bootstrap_platform(manifest_path: str) -> PlatformContext:
    """
    Bootstrap the smart home platform with all components.

    This function:
    1. Loads the manifest via load_manifest()
    2. Creates EventBus
    3. Creates FSMEngine
    4. Creates ControlTracker (if not already created)
    5. Creates HAAdapter (MockAdapter for tests)
    6. Creates CommandDispatcher with empty middleware list
    7. Creates ManualLockoutMiddleware with automation_rules and ControlTracker
    8. Adds middleware to dispatcher via add_middleware()
    9. Returns PlatformContext with all components

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

    # 5. Create HAAdapter (MockAdapter for tests)
    adapter = MockAdapter()

    # 6. Create CommandDispatcher with empty middleware list
    dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[])

    # 7. Create ManualLockoutMiddleware with automation_rules and ControlTracker
    middleware = ManualLockoutMiddleware(
        automation_rules=manifest.automation_rules,
        control_tracker=control_tracker,
    )

    # 8. Add middleware to dispatcher
    dispatcher.add_middleware(middleware)

    # Link adapter to FSM engine for event forwarding
    adapter.set_fsm_engine(fsm)

    # 9. Return PlatformContext with all components
    return PlatformContext(
        manifest=manifest,
        event_bus=event_bus,
        fsm=fsm,
        control_tracker=control_tracker,
        adapter=adapter,
        dispatcher=dispatcher,
    )


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) > 1:
        manifest_path = sys.argv[1]
    else:
        manifest_path = "instances/leonids_house/manifest.yaml"

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
