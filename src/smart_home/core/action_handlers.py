"""
Action Handlers for Smart Home Platform.

This module provides action functions that return CommandIntent objects
instead of directly calling Home Assistant services. This allows FSMs
to remain decoupled from HA implementation details.

Usage:
    registry = Registry()
    registry.register_action("turn_on_light", turn_on_light)
    registry.register_action("turn_off_light", turn_off_light)
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from .command_dispatcher import CommandIntent


def turn_on_light(state: Any, context: dict[str, Any]) -> Optional[CommandIntent]:
    """
    Create a CommandIntent to turn on a light.
    
    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.
        
    Returns:
        CommandIntent to turn on the light, or None if entity_id is missing.
    """
    entity_id = context.get("entity_id") or context.get("device_id")
    if not entity_id:
        logger.warning("turn_on_light: No entity_id in context")
        return None
    
    priority = context.get("priority", 50)
    source = context.get("source", "lighting")
    brightness = context.get("brightness")
    
    data: dict[str, Any] = {}
    if brightness is not None:
        data["brightness"] = brightness
    
    logger.info(f"Creating turn_on_light intent for {entity_id}")
    
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data=data,
        priority=priority,
        source=source,
    )


def turn_off_light(state: Any, context: dict[str, Any]) -> Optional[CommandIntent]:
    """
    Create a CommandIntent to turn off a light.
    
    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.
        
    Returns:
        CommandIntent to turn off the light, or None if entity_id is missing.
    """
    entity_id = context.get("entity_id") or context.get("device_id")
    if not entity_id:
        logger.warning("turn_off_light: No entity_id in context")
        return None
    
    priority = context.get("priority", 50)
    source = context.get("source", "lighting")
    
    logger.info(f"Creating turn_off_light intent for {entity_id}")
    
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_off",
        data={},
        priority=priority,
        source=source,
    )


def turn_on_night_light(state: Any, context: dict[str, Any]) -> Optional[CommandIntent]:
    """
    Create a CommandIntent to turn on a night light with low brightness.
    
    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.
        
    Returns:
        CommandIntent to turn on the night light, or None if entity_id is missing.
    """
    entity_id = context.get("entity_id") or context.get("device_id")
    if not entity_id:
        logger.warning("turn_on_night_light: No entity_id in context")
        return None
    
    priority = context.get("priority", 50)
    source = context.get("source", "night_light")
    brightness = context.get("brightness", 30)  # Default low brightness for night light
    
    logger.info(f"Creating turn_on_night_light intent for {entity_id} (brightness={brightness})")
    
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data={"brightness": brightness},
        priority=priority,
        source=source,
    )


def turn_off_night_light(state: Any, context: dict[str, Any]) -> Optional[CommandIntent]:
    """
    Create a CommandIntent to turn off a night light.
    
    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.
        
    Returns:
        CommandIntent to turn off the night light, or None if entity_id is missing.
    """
    entity_id = context.get("entity_id") or context.get("device_id")
    if not entity_id:
        logger.warning("turn_off_night_light: No entity_id in context")
        return None
    
    priority = context.get("priority", 50)
    source = context.get("source", "night_light")
    
    logger.info(f"Creating turn_off_night_light intent for {entity_id}")
    
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_off",
        data={},
        priority=priority,
        source=source,
    )


# Dictionary of all available action handlers for easy registration
ACTION_HANDLERS: dict[str, Any] = {
    "turn_on_light": turn_on_light,
    "turn_off_light": turn_off_light,
    "turn_on_night_light": turn_on_night_light,
    "turn_off_night_light": turn_off_night_light,
}


def register_all_actions(registry: Any) -> None:
    """
    Register all action handlers in the given registry.
    
    Args:
        registry: Registry instance to register actions in.
    """
    for name, handler in ACTION_HANDLERS.items():
        registry.register_action(name, handler)
    logger.info(f"Registered {len(ACTION_HANDLERS)} action handlers")
