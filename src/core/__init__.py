"""Smart home core module."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from core.action_handlers import release_device, turn_on_night_light
from core.command_dispatcher import CommandDispatcher, CommandIntent
from core.event_bus import EventBus
from core.fsm import FSMDefinition, FSMEngine, State, Transition
from core.middleware import ManualLockoutMiddleware, Middleware
from core.models.manifest import (
    AutomationDomainRules,
    AutomationRules,
    BehaviorConfig,
    ClimateAutomation,
    Dashboard,
    DeviceConfig,
    InstanceConfig,
    LightingAutomation,
    Manifest,
    RoomConfig,
    VentilationAutomation,
    load_manifest,
)
from core.registry import Registry
from core.scheduler import ScheduledTask, Scheduler
from core.state_persistence import StatePersistence
from core.state_store import (
    DebouncedStateStore,
    FileStateStore,
    InputTextStateStore,
    MemoryStateStore,
)


__all__ = [
    "FSMDefinition",
    "FSMEngine",
    "Registry",
    "StatePersistence",
    "State",
    "Transition",
    "EventBus",
    "Scheduler",
    "ScheduledTask",
    "Middleware",
    "ManualLockoutMiddleware",
    "CommandIntent",
    "CommandDispatcher",
    "release_device",
    "turn_on_night_light",
    "DebouncedStateStore",
    "FileStateStore",
    "InputTextStateStore",
    "MemoryStateStore",
    "AutomationRules",
    "ClimateAutomation",
    "LightingAutomation",
    "VentilationAutomation",
    "load_manifest",
    "RoomConfig",
    "Manifest",
    "InstanceConfig",
    "DeviceConfig",
    "Dashboard",
    "BehaviorConfig",
    "AutomationDomainRules",
]
