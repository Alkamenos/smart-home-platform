"""
Home Assistant Pyscript Integration Example.

This file demonstrates how to use the HAAdapter with Home Assistant's
Pyscript integration for seamless smart home automation.

Usage in Home Assistant:
1. Copy this file to /config/pyscript/smart_home_bridge.py in your HA installation
2. Ensure pyscript is installed and enabled in HA
3. The adapter will automatically handle state changes and service calls

Note: This is an example file showing the integration pattern.
      In production, adjust paths and initialization as needed.
"""

# =============================================================================
# Pyscript Integration Example for Home Assistant
# =============================================================================
# 
# This example shows how to integrate the Smart Home FSM platform with
# Home Assistant using Pyscript. Pyscript allows you to run Python code
# directly in Home Assistant with hot-reload support.
#
# Prerequisites:
# - Home Assistant with pyscript custom component installed
#   (https://github.com/custom-components/pyscript)
# - Smart Home platform code accessible from HA's Python environment
#
# Installation:
# 1. Install pyscript in HA:
#    HACS -> Integrations -> Search "pyscript" -> Install
#
# 2. Add to configuration.yaml:
#    ```yaml
#    pyscript:
#    ```
#
# 3. Copy this file to /config/pyscript/smart_home_bridge.py
#
# 4. Restart HA or reload pyscript via Developer Tools
# =============================================================================


# -----------------------------------------------------------------------------
# Import statements (adjust paths based on your HA setup)
# -----------------------------------------------------------------------------

# In a real HA pyscript environment, you would import like this:
# from src.smart_home.adapters.ha_adapter import HAAdapter
# from src.smart_home.core.fsm import FSMEngine
# from src.smart_home.core.event_bus import EventBus
# from src.smart_home.core.loader import DefinitionLoader
# from src.smart_home.core.registry import StateRegistry

# For demonstration purposes, we show the structure:

from typing import Any

# Mock imports for standalone testing (remove in actual HA deployment)
try:
    from src.smart_home.adapters.ha_adapter import HAAdapter
    from src.smart_home.core.fsm import FSMEngine
    from src.smart_home.core.event_bus import EventBus
    from src.smart_home.core.loader import DefinitionLoader
    from src.smart_home.core.registry import StateRegistry
except ImportError:
    # Fallback for environments where modules aren't available
    HAAdapter = None  # type: ignore
    FSMEngine = None  # type: ignore
    EventBus = None  # type: ignore
    DefinitionLoader = None  # type: ignore
    StateRegistry = None  # type: ignore


# -----------------------------------------------------------------------------
# Global variables (persist across pyscript reloads)
# -----------------------------------------------------------------------------

# These will be initialized when pyscript loads this file
engine: Any = None
adapter: Any = None
event_bus: Any = None
registry: Any = None
loader: Any = None


# -----------------------------------------------------------------------------
# Initialization function
# -----------------------------------------------------------------------------

def init_smart_home() -> bool:
    """
    Initialize the Smart Home FSM platform.
    
    This function sets up the core components:
    - EventBus for event distribution
    - FSMEngine for state machine logic
    - StateRegistry for entity state tracking
    - DefinitionLoader for loading FSM definitions
    - HAAdapter for HA integration
    
    Returns:
        True if initialization succeeded, False otherwise.
    
    Note:
        In pyscript, this runs automatically when the file is loaded.
    """
    global engine, adapter, event_bus, registry, loader
    
    if HAAdapter is None:
        print("[smart_home] Error: Could not import required modules")
        return False
    
    try:
        # Initialize core components
        event_bus = EventBus()
        engine = FSMEngine()
        registry = StateRegistry()
        loader = DefinitionLoader(registry=registry, engine=engine)
        
        # Link event_bus to engine (if your architecture requires it)
        engine.event_bus = event_bus  # type: ignore
        
        # Initialize HA adapter in pyscript mode
        # 'hass' is automatically available in pyscript context
        adapter = HAAdapter(
            mode="pyscript",
            engine=engine,
            hass=hass,  # noqa: F821 - 'hass' is provided by pyscript
        )
        
        # Load FSM definitions from YAML files
        # loader.load_definitions("/config/smart_home/definitions/")
        
        print("[smart_home] Initialization complete")
        return True
        
    except Exception as e:
        print(f"[smart_home] Initialization failed: {e}")
        return False


# -----------------------------------------------------------------------------
# State change handlers (Pyscript decorators)
# -----------------------------------------------------------------------------

# Example 1: Motion sensor handler
# @state_trigger("binary_sensor.kitchen_motion")
def kitchen_motion_changed(value: Any = None, old_value: Any = None) -> None:
    """
    Handle kitchen motion sensor state changes.
    
    This function is automatically called by pyscript when the
    binary_sensor.kitchen_motion entity changes state.
    
    Args:
        value: New state value ("on" or "off").
        old_value: Previous state value.
    """
    if adapter is None:
        return
    
    # Forward the state change to the FSM through the adapter
    # The adapter generates a trace_id and logs the event
    adapter.on_state_change(
        entity_id="binary_sensor.kitchen_motion",
        new_state=str(value),
        old_state=str(old_value),
        context={},
    )


# Example 2: Door sensor handler
# @state_trigger("binary_sensor.front_door")
def front_door_changed(value: Any = None, old_value: Any = None) -> None:
    """
    Handle front door sensor state changes.
    
    Args:
        value: New state value ("on" or "off").
        old_value: Previous state value.
    """
    if adapter is None:
        return
    
    adapter.on_state_change(
        entity_id="binary_sensor.front_door",
        new_state=str(value),
        old_state=str(old_value),
        context={"location": "entrance"},
    )


# Example 3: Light switch handler (manual override)
# @state_trigger("switch.kitchen_light")
def kitchen_light_switch_changed(value: Any = None, old_value: Any = None) -> None:
    """
    Handle manual light switch changes.
    
    This allows the FSM to detect when a user manually overrides
    the automation.
    
    Args:
        value: New state value ("on" or "off").
        old_value: Previous state value.
    """
    if adapter is None:
        return
    
    adapter.on_state_change(
        entity_id="switch.kitchen_light",
        new_state=str(value),
        old_value=str(old_value),
        context={"override": True},
    )


# -----------------------------------------------------------------------------
# Service call examples (called from FSM actions)
# -----------------------------------------------------------------------------

async def turn_on_light(entity_id: str, brightness: int | None = None) -> bool:
    """
    Turn on a light via HA adapter.
    
    This function can be registered as an action in the FSM and
    will be called when a transition occurs.
    
    Args:
        entity_id: Light entity ID (e.g., "light.kitchen").
        brightness: Optional brightness level (0-255).
    
    Returns:
        True if service call succeeded, False otherwise.
    
    Example:
        # Register as FSM action:
        engine.register_action("turn_on_kitchen_light", lambda ctx: turn_on_light("light.kitchen"))
    """
    if adapter is None:
        return False
    
    data = {}
    if brightness is not None:
        data["brightness"] = brightness
    
    # The adapter handles trace_id propagation automatically
    return await adapter.call_service(
        domain="light",
        service="turn_on",
        entity_id=entity_id,
        data=data,
        trace_id=None,  # Adapter will generate one if not provided
    )


async def turn_off_light(entity_id: str) -> bool:
    """
    Turn off a light via HA adapter.
    
    Args:
        entity_id: Light entity ID.
    
    Returns:
        True if service call succeeded, False otherwise.
    """
    if adapter is None:
        return False
    
    return await adapter.call_service(
        domain="light",
        service="turn_off",
        entity_id=entity_id,
    )


async def notify_message(message: str) -> bool:
    """
    Send a notification via HA.
    
    Args:
        message: Notification message text.
    
    Returns:
        True if notification was sent, False otherwise.
    """
    if adapter is None:
        return False
    
    return await adapter.call_service(
        domain="persistent_notification",
        service="create",
        entity_id="",
        data={
            "title": "Smart Home Alert",
            "message": message,
        },
    )


# -----------------------------------------------------------------------------
# Startup hook (pyscript lifecycle)
# -----------------------------------------------------------------------------

def pyscript_startup() -> None:
    """
    Called by pyscript when the script is first loaded.
    
    This is the entry point for initialization.
    """
    print("[smart_home] pyscript_startup called")
    init_smart_home()


# -----------------------------------------------------------------------------
# Shutdown hook (pyscript lifecycle)
# -----------------------------------------------------------------------------

async def pyscript_shutdown() -> None:
    """
    Called by pyscript before the script is unloaded.
    
    Performs graceful shutdown of the adapter and engine.
    """
    print("[smart_home] pyscript_shutdown called")
    
    if adapter is not None:
        await adapter.stop()
    
    if engine is not None:
        await engine.shutdown()
    
    print("[smart_home] Shutdown complete")


# -----------------------------------------------------------------------------
# Run initialization on load
# -----------------------------------------------------------------------------

# In pyscript, top-level code runs on load
# We call the startup hook explicitly
pyscript_startup()
