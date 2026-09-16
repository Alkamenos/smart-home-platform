"""Models package for Smart Home Platform."""

from .manifest import (
    AnyDevice,
    AutomationDomainRules,
    AutomationRules,
    BehaviorConfig,
    # Backward compatibility aliases
    ClimateAutomation,
    Dashboard,
    DeviceConfig,
    # Core models
    InstanceConfig,
    InstanceInfo,
    LightingAutomation,
    LightMotionDevice,
    Manifest,
    RoomConfig,
    VentilationAutomation,
    Zone,
    # Loader
    load_manifest,
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
]
