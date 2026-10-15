"""Модель автомата: состояние, переход, решение, определение (BACKLOG B80).

Данные отделены от движка. `engine.py` вырос до 1800 строк, где рядом жили и
описание автомата, и его исполнение; читать такое нельзя, а менять — страшно.
Здесь только неизменяемые структуры и один чистый предикат: они не знают ни о
шине событий, ни о хранилище, ни о командах.

Имена остаются доступными и из `core.fsm.engine` — там стоит реэкспорт: разрез
не меняет поведения и не ломает ни один существующий импорт.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from core.commands.dispatcher import CommandIntent


def is_measurement(value: Any) -> bool:
    """Похоже ли значение на показание датчика.

    Показание — число или строка, приводимая к числу. `None`, `unavailable`,
    `unknown` и прочие строки показанием не являются: по ним выносить решение
    нельзя, и отказ должен называться «данных не было», а не «значение не
    подходит». Иначе молчащий датчик неотличим от работающего.

    Args:
        value: Значение из контекста перехода.

    Returns:
        True, если значение можно трактовать как измерение.
    """
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return False
        return True
    return False


# @dataclass (frozen=True)
@dataclass
class State:
    """
    Immutable representation of the current state of an entity.

    Attributes:
        current_state: The name/identifier of the current state.
        entered_at: Unix timestamp when this state was entered.
        context: Dictionary for internal memory (e.g., last manual intervention time).
    """

    current_state: str
    entered_at: float
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    """
    Immutable definition of a state transition.

    Attributes:
        from_state: The source state for this transition.
        to_state: The destination state after transition.
        trigger: The event name that triggers this transition.
        guard: Optional callable condition function that must return True.
        action: Optional callable action function to execute on transition.
            Actions now return CommandIntent (or None) instead of calling HA directly.
        timeout_sec: Optional timeout in seconds to auto-trigger 'timeout' event.
        priority: Optional priority for transition selection (higher = more important).
        reason: Optional human-readable reason for the transition.
        attributes: Optional dict of attributes to attach to the transition.
        manual_lockout_min: Optional lockout time in minutes for manual transitions.
    """

    from_state: str
    to_state: str
    trigger: str
    guard: Callable[..., bool] | None = None
    action: Callable[..., CommandIntent | None] | None = None
    timeout_sec: float | None = None
    priority: int = 0
    reason: str | None = None
    attributes: dict[str, Any] | None = None
    manual_lockout_min: float | None = None


@dataclass(frozen=True)
class Decision:
    """
    Immutable record of an FSM decision: what was done and why.

    Attributes:
        at: Unix timestamp when the decision was made.
        outcome: The decision outcome: 'on', 'off', 'none', or 'denied'.
        reason_code: Machine-readable reason code from GUARD_DENIAL_REASONS or action.
        reason_text: Human-readable reason (must be non-empty always, except outcome='none').
        trigger: The event name that triggered this decision.
    """

    at: float
    outcome: str  # 'on' | 'off' | 'none' | 'denied'
    reason_code: str | None
    reason_text: str
    trigger: str | None


@dataclass(frozen=True)
class FSMDefinition:
    """
    Immutable definition of a Finite State Machine.

    Attributes:
        entity_id: Unique identifier for the entity using this FSM.
        initial_state: The starting state name.
        states: Tuple of valid state names.
        transitions: Tuple of Transition objects defining state changes.
        debounce_sec: Minimum time between state changes to prevent bouncing.
        params: Optional parameters from BehaviorConfig for template injection.
        target_device_id: Original device ID for routing events to the correct device.
        room: Room the device belongs to; conditions read it from the transition
            context (ночное окно разрешает свет в одних комнатах и запрещает в
            других — без комнаты это правило невыполнимо).
        initial: Alias for initial_state for backward compatibility.
    """

    entity_id: str
    initial_state: str
    states: tuple[str, ...]
    transitions: tuple[Transition, ...]
    debounce_sec: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)
    target_device_id: str | None = None
    room: str | None = None

    @property
    def initial(self) -> str:
        """Alias for initial_state for backward compatibility."""
        return self.initial_state
