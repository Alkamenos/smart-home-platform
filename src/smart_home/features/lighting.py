"""
Lighting feature module - provides lighting automation templates.

This module defines action handlers and FSM definitions for the lighting feature.
It is used by tests and CLI tools to create lighting automations.
"""

from src.smart_home.core.fsm import FSMDefinition, Transition
from src.smart_home.core.command_dispatcher import CommandIntent


async def turn_on_light(state, context: dict):
    """Turn on light with standard brightness."""
    entity_id = context.get("entity_id", "light.unknown")
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data={"brightness": 255},
        priority=10,
        source="lighting",
    )


async def turn_off_light(state, context: dict):
    """Turn off light."""
    entity_id = context.get("entity_id", "light.unknown")
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_off",
        data={},
        priority=10,
        source="lighting",
    )


async def turn_on_night_light(state, context: dict):
    """Turn on night light with low brightness."""
    entity_id = context.get("entity_id", "light.unknown")
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data={"brightness": 50},
        priority=20,
        source="night_light",
    )


async def turn_off_night_light(state, context: dict):
    """Turn off night light."""
    entity_id = context.get("entity_id", "light.unknown")
    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_off",
        data={},
        priority=20,
        source="night_light",
    )


def create_lighting_automations(rooms: list[str]) -> list[FSMDefinition]:
    """
    Create lighting FSM definitions for given rooms.
    
    Args:
        rooms: List of room IDs (e.g., ["living_room", "kitchen"])
    
    Returns:
        List of FSMDefinition objects for each room's light
    """
    definitions = []
    
    for room in rooms:
        entity_id = f"light.{room}"
        
        transitions = (
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                action="turn_on_light",
            ),
            Transition(
                from_state="ON_MOTION",
                to_state="OFF",
                trigger="timeout",
                action="turn_off_light",
                timeout_sec=300.0,
            ),
            Transition(
                from_state="OFF",
                to_state="ON_NIGHT",
                trigger="motion_detected",
                guard="is_night_time",
                action="turn_on_night_light",
            ),
            Transition(
                from_state="ON_NIGHT",
                to_state="OFF",
                trigger="timeout",
                action="turn_off_night_light",
                timeout_sec=60.0,
            ),
        )
        
        fsm_def = FSMDefinition(
            entity_id=entity_id,
            initial_state="OFF",
            states=("OFF", "ON_MOTION", "ON_NIGHT"),
            transitions=transitions,
            debounce_sec=0.5,
        )
        definitions.append(fsm_def)
    
    return definitions
