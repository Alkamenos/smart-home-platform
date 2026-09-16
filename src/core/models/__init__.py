"""Models package for Smart Home Platform."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from .manifest import (  # Backward compatibility aliases; Core models; Loader
    AnyDevice,
    AutomationDomainRules,
    AutomationRules,
    BehaviorConfig,
    ClimateAutomation,
    Dashboard,
    DeviceConfig,
    InstanceConfig,
    InstanceInfo,
    LightingAutomation,
    LightMotionDevice,
    Manifest,
    RoomConfig,
    VentilationAutomation,
    Zone,
    load_manifest,
)
from .guards import (
    TimeGuardConfig,
    StateGuardConfig,
    NumericGuardConfig,
    ScheduleGuardConfig,
    CompositeGuardConfig,
    GuardFactoryModel,
)


__all__ = [
    "InstanceConfig",
    "BehaviorConfig",
    "DeviceConfig",
    "RoomConfig",
    "AutomationDomainRules",
    "AutomationRules",
    "Manifest",
    "Dashboard",
    "load_manifest",
    # Aliases
    "ClimateAutomation",
    "LightingAutomation",
    "VentilationAutomation",
    "AnyDevice",
    "LightMotionDevice",
    "Zone",
    "InstanceInfo",
    # Guard configs
    "TimeGuardConfig",
    "StateGuardConfig",
    "NumericGuardConfig",
    "ScheduleGuardConfig",
    "CompositeGuardConfig",
    "GuardFactoryModel",
]
