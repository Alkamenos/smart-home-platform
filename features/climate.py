"""
Climate Feature - Автоматы климата

Декларативное описание автоматов для управления климатом.
Состояния: IDLE, HEATING, COOLING, SAFETY_LOCKOUT, AWAY
"""

from __future__ import annotations
import sys
import os

# Добавляем parent directory в path для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fsm import FSMDefinition, Transition


def create_climate_automations(zones: list[str]) -> list[FSMDefinition]:
    """
    Создаёт автоматы для всех климатических зон
    
    Args:
        zones: Список зон (например, ["living_room", "bedroom"])
    
    Returns:
        Список определений FSM
    """
    definitions = []
    
    for zone in zones:
        entity_id = f"climate.{zone}"
        
        definition = FSMDefinition(
            entity_id=entity_id,
            states=("IDLE", "HEATING", "COOLING", "SAFETY_LOCKOUT", "AWAY"),
            initial="IDLE",
            triggers_mapping={
                "temp_low": f"sensor.{zone}_temperature",
                "temp_high": f"sensor.{zone}_temperature",
                "temp_reached": f"sensor.{zone}_temperature",
                "away_mode_on": f"input_boolean.{zone}_away_mode",
                "away_mode_off": f"input_boolean.{zone}_away_mode",
                "safety_alarm": f"binary_sensor.{zone}_safety_alarm",
                "safety_reset": f"binary_sensor.{zone}_safety_alarm",
            },
            transitions=(
                # Включение нагрева
                Transition(
                    from_state="IDLE",
                    to_state="HEATING",
                    trigger="temp_low",
                    guard=lambda ctx, z=zone: (
                        ctx.get(f"{z}_temp_current", 0) < ctx.get(f"{z}_temp_target", 0) - 0.5 and
                        ctx.get(f"{z}_mode", "auto") in ("heat", "auto")
                    ),
                    priority=30,
                    reason="Температура ниже целевой"
                ),
                
                # Выключение нагрева
                Transition(
                    from_state="HEATING",
                    to_state="IDLE",
                    trigger="temp_reached",
                    guard=lambda ctx, z=zone: (
                        ctx.get(f"{z}_temp_current", 0) >= ctx.get(f"{z}_temp_target", 0)
                    ),
                    priority=30,
                    reason="Температура достигнута"
                ),
                
                # Включение охлаждения
                Transition(
                    from_state="IDLE",
                    to_state="COOLING",
                    trigger="temp_high",
                    guard=lambda ctx, z=zone: (
                        ctx.get(f"{z}_temp_current", 0) > ctx.get(f"{z}_temp_target", 0) + 0.5 and
                        ctx.get(f"{z}_mode", "auto") in ("cool", "auto")
                    ),
                    priority=30,
                    reason="Температура выше целевой"
                ),
                
                # Выключение охлаждения
                Transition(
                    from_state="COOLING",
                    to_state="IDLE",
                    trigger="temp_reached",
                    guard=lambda ctx, z=zone: (
                        ctx.get(f"{z}_temp_current", 0) <= ctx.get(f"{z}_temp_target", 0)
                    ),
                    priority=30,
                    reason="Температура достигнута"
                ),
                
                # Режим отсутствия
                Transition(
                    from_state="*",
                    to_state="AWAY",
                    trigger="away_mode_on",
                    priority=40,
                    reason="Режим отсутствия включён"
                ),
                
                Transition(
                    from_state="AWAY",
                    to_state="IDLE",
                    trigger="away_mode_off",
                    priority=40,
                    reason="Режим отсутствия выключен"
                ),
                
                # Блокировка безопасности (самый высокий приоритет)
                Transition(
                    from_state="*",
                    to_state="SAFETY_LOCKOUT",
                    trigger="safety_alarm",
                    priority=200,
                    reason="Сработала система безопасности"
                ),
                
                # Сброс блокировки
                Transition(
                    from_state="SAFETY_LOCKOUT",
                    to_state="IDLE",
                    trigger="safety_reset",
                    priority=200,
                    reason="Блокировка сброшена"
                ),
            )
        )
        
        definitions.append(definition)
    
    return definitions
