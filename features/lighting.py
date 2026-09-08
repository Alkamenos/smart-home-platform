"""
Lighting Feature - Автоматы освещения

Декларативное описание автоматов для управления освещением.
Состояния: OFF, ON_SCHEDULE, ON_MOTION, PARTY, NIGHTLIGHT, MANUAL
"""

from __future__ import annotations
import sys
import os
import time  # Для расчёта таймаутов ручного управления

# Добавляем parent directory в path для импорта core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.fsm import FSMDefinition, Transition


def create_lighting_automations(rooms: list[str]) -> list[FSMDefinition]:
    """
    Создаёт автоматы для всех комнат
    
    Args:
        rooms: Список комнат (например, ["living_room", "bedroom"])
    
    Returns:
        Список определений FSM
    """
    definitions = []
    
    for room in rooms:
        entity_id = f"light.{room}"
        
        definition = FSMDefinition(
            entity_id=entity_id,
            states=("OFF", "ON_SCHEDULE", "ON_MOTION", "PARTY", "NIGHTLIGHT", "MANUAL"),
            initial="OFF",
            transitions=(
                # Включение по расписанию
                Transition(
                    from_state="OFF",
                    to_state="ON_SCHEDULE",
                    trigger="schedule_on",
                    guard=lambda ctx, r=room: (
                        ctx.get(f"{r}_is_schedule_time", False) and
                        not ctx.get(f"{r}_is_night_time", False)
                    ),
                    priority=10,
                    reason="Включение по расписанию"
                ),
                
                # Выключение по расписанию
                Transition(
                    from_state="ON_SCHEDULE",
                    to_state="OFF",
                    trigger="schedule_off",
                    guard=lambda ctx, r=room: not ctx.get(f"{r}_is_schedule_time", False),
                    priority=10,
                    reason="Выключение по расписанию"
                ),
                
                # Включение по движению
                Transition(
                    from_state=("OFF", "ON_SCHEDULE"),
                    to_state="ON_MOTION",
                    trigger="motion_detected",
                    guard=lambda ctx, r=room: (
                        ctx.get(f"{r}_motion_sensor", False) and
                        ctx.get(f"{r}_motion_enabled", True)
                    ),
                    priority=20,
                    reason="Обнаружено движение"
                ),
                
                # Выключение при отсутствии движения
                Transition(
                    from_state="ON_MOTION",
                    to_state="OFF",
                    trigger="motion_cleared",
                    guard=lambda ctx, r=room: not ctx.get(f"{r}_motion_sensor", False),
                    priority=20,
                    reason="Движение не обнаружено"
                ),
                
                # Режим вечеринки
                Transition(
                    from_state="*",
                    to_state="PARTY",
                    trigger="party_mode_on",
                    priority=50,
                    reason="Режим вечеринки включён"
                ),
                
                Transition(
                    from_state="PARTY",
                    to_state="OFF",
                    trigger="party_mode_off",
                    priority=50,
                    reason="Режим вечеринки выключен"
                ),
                
                # Ночной режим
                Transition(
                    from_state="*",
                    to_state="NIGHTLIGHT",
                    trigger="night_mode_on",
                    guard=lambda ctx, r=room: ctx.get(f"{r}_is_night_time", False),
                    priority=40,
                    reason="Ночной режим"
                ),
                
                Transition(
                    from_state="NIGHTLIGHT",
                    to_state="OFF",
                    trigger="night_mode_off",
                    priority=40,
                    reason="Ночной режим выключен"
                ),
                
                # Ручное вмешательство (самый высокий приоритет)
                # При переходе сохраняем timestamp в контексте для корректного расчёта таймаута
                Transition(
                    from_state="*",
                    to_state="MANUAL",
                    trigger="manual_change",
                    priority=100,
                    reason="Ручное вмешательство",
                    # Сохраняем время ручного вмешательства в контекст FSM
                    action=lambda ctx, r=room: ctx.update({f"{r}_manual_entered_at": time.time()})
                ),
                
                # Возврат из MANUAL после таймаута (60 минут)
                Transition(
                    from_state="MANUAL",
                    to_state="OFF",
                    trigger="timeout",
                    guard=lambda ctx, r=room: (
                        lambda entered_at=ctx.get(f"{r}_manual_entered_at", 0):
                        entered_at > 0 and (time.time() - entered_at) / 60 >= 60
                    )(),
                    priority=50,
                    reason="Автоматическое восстановление после ручного управления"
                ),
            )
        )
        
        definitions.append(definition)
    
    return definitions
