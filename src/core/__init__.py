"""Smart home core module."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from core.action_handlers import release_device, turn_on_night_light
from core.commands.dispatcher import CommandDispatcher, CommandIntent
from core.commands.middleware import ManualLockoutMiddleware, Middleware
from core.events.event_bus import EventBus
from core.fsm.engine import FSMDefinition, FSMEngine, State, Transition
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
from core.persistence.state_persistence import StatePersistence
from core.persistence.state_store import (
    DebouncedStateStore,
    FileStateStore,
    InputTextStateStore,
    MemoryStateStore,
)
from core.registry import Registry
from core.scheduling.scheduler import ScheduledTask, Scheduler


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
