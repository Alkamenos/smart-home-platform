"""
FSM (Finite State Machine) Engine for Smart Home Platform.

This module provides an immutable, async-first FSM engine designed for
smart home automation scenarios with support for guards, actions, timeouts,
and debounce protection.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_TRANSITIONED,
    GUARD_DENIAL_REASONS,
    OUTCOME_REJECTED,
    OUTCOME_TRANSITIONED,
    REASON_DEBOUNCED,
    REASON_GUARD_DATA_MISSING,
    REASON_GUARD_FAILED,
    REASON_NO_STATE,
    REASON_NO_TRANSITION,
    REASON_TEXT,
    REASON_UNKNOWN_ENTITY,
    build_transition_payload,
)
from core.models.manifest import AutomationDomainRules


if TYPE_CHECKING:
    from core.commands.dispatcher import CommandDispatcher, CommandIntent
    from core.events.event_bus import EventBus
    from core.persistence.state_persistence import StatePersistence


# Сколько ждать завершения задач публикации при остановке движка, прежде чем
# отменить их (FR-012).
PUBLISH_DRAIN_TIMEOUT_SEC = 1.0

# Флаг, возвращающий прежнее поведение: каждый отказ пишется в журнал.
ENV_LOG_REJECTIONS = "FSM_LOG_REJECTIONS"

# Значения флага, которые его включают. Всё остальное, включая пустую строку,
# опечатку и отсутствие переменной, флаг не включает: иначе опечатка в
# настройке возвращала бы 80% шума в журнал молча.
_FLAG_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _flag_enabled(name: str) -> bool:
    """Включён ли булев флаг окружения.

    Args:
        name: Имя переменной окружения.

    Returns:
        True, если переменная задана одним из значений «да».
    """
    return os.environ.get(name, "").strip().lower() in _FLAG_TRUE_VALUES


def loop_time() -> float:
    """Получить монотонное время текущего цикла событий.

    Вне работающего цикла возвращается 0.0: `register_definition` может быть
    вызван синхронно (сборка контейнера, тесты), и отсутствие цикла не должно
    приводить к отказу регистрации автомата (FR-016).

    Returns:
        Монотонное время цикла событий либо 0.0, если цикл недоступен.
    """
    try:
        return asyncio.get_event_loop().time()
    except RuntimeError:
        return 0.0


def _is_measurement(value: Any) -> bool:
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


#: События, чьи команды обходят блокировку человека: это правила безопасности
#: («не горит всю ночь»), а не удобство автоматики.
#:
#: ``sleep_started`` здесь потому же: модификатор «мы спим» гасит свет во
#: всех состояниях, включая включённый человеком из приложения — свет, который
#: горит, пока все спят, важнее часа локаута.
#:
#: ``sunrise_started``, ``sunset_started`` и ``day_started`` — события смены
#: суток: они включают и выключают вечерний свет по расписанию дня, и человек,
#: щёлкнувший гирлянду в приложении, не должен оставлять её гореть до утра.
SAFETY_EVENTS: frozenset[str] = frozenset(
    {"quiet_hours_started", "sleep_started", "sunset_started", "sunrise_started", "day_started"}
)


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


#: Параметры поведения, которые входят в контекст автомата. Нужны для чистки
#: устаревших: контекст состояния накопительный (``{**current_state.context}``),
#: и параметр, **убранный** из манифеста, жил бы в нём вечно. Боевой дефект
#: 2026-10-12: ``managed_by_hardware: true`` из манифеста до 2026-10-10 остался
#: в ``state.json`` гостиной, и конвектор отказывал при любой уставке.
KNOWN_BEHAVIOR_PARAM_KEYS: frozenset[str] = frozenset(
    {
        # Параметры шаблонов (см. src/features/*.yaml и спеки).
        "heater_timer",
        "run_minutes",
        "hysteresis",
        "managed_by_hardware",
        "off_by",
        "humidity_threshold",
        "motion_timeout_sec",
        "brightness",
        "schedule",
        "target_temp",
        # Параметры вентиляции (спека 014, data-model.md §5).
        "mode_supply",
        "mode_summer",
        "mode_winter",
        "mode_night",
        "mode_airing",
        "mode_exhaust",
        "speed_normal",
        "speed_delta_gain",
        "speed_night_max",
        "delta_deadband",
        "airing_seconds",
        "source_room",
        "winter_mode_threshold",
        # Параметры переработки вентиляции по уточнениям владельца (спека 014,
        # T085–T088): роль устройства и пороги санузла тоже живут в контексте,
        # и убранные из манифеста должны вычищаться, как и остальные.
        "ventilation_role",
        "supply_delta_threshold",
        "exhaust_seconds",
        "exhaust_temp_threshold",
        "exhaust_humidity_threshold",
        # Скорость по уточнению владельца 2026-10-12 (research.md D22, FR-052):
        # обычная скорость, минимум, опорная температура улицы и шаг снижения.
        # Удалённые из манифеста mode_supply/speed_delta_gain/speed_night_max/
        # delta_deadband/supply_delta_threshold остаются выше: их старые версии
        # ещё лежат в сохранённом состоянии автоматов и должны вычищаться.
        "speed_min",
        "speed_cold_reference",
        "speed_cold_gain",
    }
    # Доменные правила дома фабрика превращает в параметры поведения (T012
    # спеки 014), значит и они попадают в контекст состояния.
    | frozenset(AutomationDomainRules.model_fields)
)


def sanitise_stale_params(context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Убрать из накопленного контекста параметры, которых больше нет в манифесте.

    Параметры принадлежат манифесту, а не состоянию: они дополняются при
    каждом переходе (``update``), поэтому их безопасно вычищать из накопления.
    Чистится только известное — ``KNOWN_BEHAVIOR_PARAM_KEYS``: белый список
    оператор для чужих ключей сломал бы чужое поведение быстрее, чем нашлось бы.

    Args:
        context: Накопленный контекст состояния автомата.
        params: Параметры поведения из манифеста для этого автомата.

    Returns:
        Копия контекста без устаревших параметров.
    """
    cleaned = dict(context)
    for key in KNOWN_BEHAVIOR_PARAM_KEYS:
        if key not in params and key in cleaned:
            logger.debug(f"Убран устаревший параметр {key} из контекста перехода")
            del cleaned[key]
    return cleaned


#: Шаблоны, решения которых разбираются утром по журналу. Для них каждое
#: решение (и разрешение, и отказ) пишется видимо и без ограничения частоты:
#: по одной записи должно быть видно, что пришло, что решили и почему.
#: Остальные автоматы (свет) остаются при прежнем поведении: их события — фон,
#: и подробный разбор каждого затопил бы полезное (`.ai/04_RULES.md`).
DIAGNOSTIC_TEMPLATES: Final[tuple[str, ...]] = (
    "climate_control",
    "ventilation_modes",
    "humidity_ventilation",
)

#: Ключи контекста, которые попадают в диагностическую запись решения. Значения
#: приходят из события датчика и глобальных сущностей, поэтому именно они дают
#: утренний ответ на вопрос «почему не сработало». `heating_active` здесь с
#: 2026-10-12 не влияет на решения (FR-055), но остаётся в записи как ответ на
#: вопрос «шёл ли обогрев, когда включался приток».
DIAGNOSTIC_CONTEXT_KEYS: Final[tuple[str, ...]] = (
    "temperature",
    "humidity",
    "outside_temperature",
    "is_winter",
    "heating_active",
    "ventilation_role",
    "ventilation_on",
    "ventilation_enabled",
    "airing_on",
    "exhaust_on",
    "sleep_modifier_on",
    "climate_setpoint",
    "comfort_max",
    "ac_allowed",
    "climate_enabled",
    "chosen_mode",
    "percentage",
)


def _is_diagnostic_entity(entity_id: str) -> bool:
    """Относится ли автомат к климату или вентиляции.

    Имя автомата строится как ``{устройство}_{шаблон}_{приоритет}`` (ADR-003),
    поэтому шаблон виден в самом идентификаторе.

    Args:
        entity_id: Идентификатор автомата.

    Returns:
        True, если решения автомата пишутся подробно.
    """
    return any(template in entity_id for template in DIAGNOSTIC_TEMPLATES)


def _diagnostic_context(context: dict[str, Any]) -> dict[str, Any]:
    """Отобрать значимые для разбора ключи контекста.

    Args:
        context: Контекст перехода.

    Returns:
        Словарь только тех ключей, что есть в контексте.
    """
    return {key: context[key] for key in DIAGNOSTIC_CONTEXT_KEYS if key in context}


class FSMEngine:
    """
    Async FSM Engine for smart home entities.

    Manages state machines for multiple entities with support for:
    - Guard conditions evaluation
    - Action execution on transitions
    - Timeout-based automatic transitions
    - Debounce protection against rapid state changes
    - Publication of every performed or rejected transition to the event bus
    - Comprehensive logging via loguru
    """

    def __init__(
        self,
        command_dispatcher: CommandDispatcher | None = None,
        persistence: StatePersistence | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._states: dict[str, State] = {}
        self._definitions: dict[str, FSMDefinition] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._last_transition_time: dict[str, float] = {}
        # Настенное время последнего перехода в формате интерфейса: монотонные
        # часы цикла (State.entered_at) несравнимы с настенным временем и
        # бессмысленны для показа пользователю (R-04, FR-017).
        self._last_transition_wall: dict[str, str] = {}
        self._guards: dict[str, Callable[..., bool]] = {}
        self._actions: dict[str, Callable[..., Any]] = {}
        self._dispatcher = command_dispatcher
        self._persistence = persistence
        self._event_bus = event_bus
        self._publish_tasks: set[asyncio.Task[None]] = set()
        # Счётчики отказов по причинам: наблюдаемость не теряется при молчании
        # в журнале, а переезжает туда, где полезна (см. `_record_rejection`).
        self._rejection_counts: dict[str, int] = {}
        # Сущности, об отказе по которым уже сказано в журнале. Отказ честный —
        # сущности действительно нет в манифесте, — но повторять его тысячи раз
        # незачем: в доме синхронизировано 1489 устройств против 6 в манифесте,
        # и это давало две строки журнала на каждое изменение состояния, то есть
        # 80% объёма. Число строк растёт с числом РАЗЛИЧНЫХ сущностей, а не с
        # числом событий.
        self._reported_rejections: set[tuple[str, str]] = set()
        # Флаг возвращает прежнее поведение целиком — на случай разбора в доме,
        # где шум полезен. Нераспознанное значение флага шум не включает: тот же
        # принцип, что и в `SHADOW_MODE`.
        self._log_every_rejection = _flag_enabled(ENV_LOG_REJECTIONS)
        # Последнее решение по каждому автомату (требование FR-005, FR-008).
        # Хранится только одно: карточка отвечает на вопрос «почему сейчас», а не
        # «что было ночью» — за историю отвечает журнал.
        self._decisions: dict[str, Decision] = {}

    def rejection_counts(self) -> dict[str, int]:
        """Сколько отказов было по каждой причине.

        Возвращается копия: счётчик доступен наружу для диагностики, но менять
        его извне нельзя.

        Returns:
            Словарь «причина → число отказов».
        """
        return dict(self._rejection_counts)

    def _record_rejection(self, entity_id: str, event: str, reason: str) -> None:
        """Учесть отказ и решить, стоит ли о нём писать в журнал.

        Args:
            entity_id: Идентификатор сущности, по которой отказ.
            event: Событие-триггер.
            reason: Причина отказа.
        """
        self._rejection_counts[reason] = self._rejection_counts.get(reason, 0) + 1

        # Record the decision (T005, FR-005)
        self._record_decision(
            entity_id=entity_id,
            outcome="denied",
            reason_code=reason,
            reason_text=None,  # Will be determined from reason_code
            trigger=event,
        )

        if _is_diagnostic_entity(entity_id):
            # Климат и вентиляция: отказ виден на каждом событии, а не один раз
            # на сущность. Причина и событие названы прямо — утренний разбор
            # должен прочитать «почему не сработало» без обращения к коду.
            logger.warning(
                f"FSMEngine: решение отказано — {entity_id}, событие '{event}', причина {reason}"
            )
            return

        if self._log_every_rejection:
            # Флаг возвращает прежнее поведение целиком: каждый отказ пишется.
            logger.warning(
                f"FSMEngine: отказ по сущности {entity_id} ({reason}), событие '{event}'"
            )
            return

        key = (entity_id, reason)
        if key in self._reported_rejections:
            return
        self._reported_rejections.add(key)
        logger.warning(
            f"FSMEngine: отказ по сущности {entity_id} ({reason}); "
            f"повторные отказы этой сущности в журнал не пишутся, счётчик — "
            f"в rejection_counts()"
        )

    def note_transition(self, entity_id: str, wall_clock: str | None = None) -> None:
        """Зафиксировать настенное время перехода автомата.

        Вызывается при каждом выполненном переходе. Хранится отдельно от
        состояния, поэтому правила переходов, debounce и таймауты не затрагиваются.

        Args:
            entity_id: Идентификатор автомата.
            wall_clock: Время перехода в формате ISO-8601; по умолчанию — текущее.
        """
        from core.events.fsm_events import now_timestamp

        self._last_transition_wall[entity_id] = wall_clock or now_timestamp()

    def get_last_transition_time(self, entity_id: str) -> str | None:
        """Получить настенное время последнего перехода автомата.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Время в формате ISO-8601 либо None, если переходов не было.
        """
        return self._last_transition_wall.get(entity_id)

    def set_command_dispatcher(self, command_dispatcher: CommandDispatcher) -> None:
        """Связать движок с диспетчером команд после его создания.

        Диспетчер создаётся после движка (он зависит от адаптера, а адаптер — от
        движка), поэтому циклическая зависимость разрывается связыванием
        из контейнера (R-01).

        Args:
            command_dispatcher: Диспетчер команд, которому передаются интенты.
        """
        self._dispatcher = command_dispatcher

    def _schedule_publish(self, event_type: str, payload: dict[str, Any], trace_id: str) -> None:
        """Запланировать публикацию события перехода отдельной задачей.

        Доставка неблокирующая: медленный подписчик не задерживает выполнение
        перехода (FR-014, SC-015). Задача отслеживается, чтобы остановка движка
        не оставляла висящих задач.

        Args:
            event_type: Имя события (`fsm.transitioned` или `fsm.rejected`).
            payload: Полезная нагрузка события.
            trace_id: Идентификатор трассы текущего срабатывания.
        """
        if self._event_bus is None:
            return

        bus = self._event_bus
        task = asyncio.create_task(bus.publish(event_type, payload, trace_id))
        self._publish_tasks.add(task)
        task.add_done_callback(self._publish_tasks.discard)

    def _publish_transition(
        self,
        entity_id: str,
        event: str,
        from_state: str | None,
        to_state: str,
        trace_id: str,
    ) -> None:
        """Опубликовать выполненный переход.

        Args:
            entity_id: Идентификатор автомата.
            event: Событие-триггер.
            from_state: Предыдущее состояние.
            to_state: Новое состояние.
            trace_id: Идентификатор трассы.
        """
        definition = self._definitions.get(entity_id)
        device_id = definition.target_device_id if definition else None
        payload = build_transition_payload(
            fsm_id=entity_id,
            device_id=device_id or entity_id,
            from_state=from_state,
            to_state=to_state,
            event=event,
            outcome=OUTCOME_TRANSITIONED,
            trace_id=trace_id,
        )
        self._schedule_publish(EVENT_FSM_TRANSITIONED, payload, trace_id)

    def _publish_rejection(
        self,
        entity_id: str,
        event: str,
        from_state: str | None,
        reason: str,
        trace_id: str,
    ) -> None:
        """Опубликовать отказ в переходе с указанием причины (FR-004).

        Args:
            entity_id: Идентификатор автомата.
            event: Событие-триггер.
            from_state: Состояние, из которого переход не состоялся.
            reason: Причина отказа.
            trace_id: Идентификатор трассы.
        """
        definition = self._definitions.get(entity_id)
        device_id = definition.target_device_id if definition else None
        payload = build_transition_payload(
            fsm_id=entity_id,
            device_id=device_id or entity_id,
            from_state=from_state,
            to_state=None,
            event=event,
            outcome=OUTCOME_REJECTED,
            trace_id=trace_id,
            reason=reason,
        )
        self._schedule_publish(EVENT_FSM_REJECTED, payload, trace_id)

    def register_definition(self, definition: FSMDefinition, restore_state: bool = True) -> None:
        """Register an FSM definition for an entity.

        Args:
            definition: The FSM definition to register.
            restore_state: If True, attempt to restore saved state from persistence.
        """
        self._definitions[definition.entity_id] = definition

        # Check if we have a persisted state to restore
        restored_state: tuple[str, dict] | None = None
        if restore_state and self._persistence is not None:
            restored_state = self._persistence.load_state(definition.entity_id)

        if restored_state is not None:
            saved_state, saved_context = restored_state
            # Validate that the saved state is valid for this FSM
            if saved_state in definition.states:
                # Время входа берётся из сохранённых данных, а не подставляется
                # заново: `entered_at` — монотонные часы цикла, поэтому при
                # восстановлении «сейчас» нужно откатить на то время, которое
                # состояние уже пролежало. Иначе остаток отложенного перехода
                # считался бы от старта контейнера (Known Issue #78).
                restored_age = self._restored_state_age(definition.entity_id)
                entered_at = loop_time() - restored_age
                self._states[definition.entity_id] = State(
                    current_state=saved_state,
                    entered_at=entered_at,
                    context=saved_context,
                )
                logger.info(
                    f"Registered FSM for entity {definition.entity_id} with restored state "
                    f"'{saved_state}' (state held for {restored_age:.1f}s)"
                )
                # Таймер восстанавливается вместе с состоянием: без него
                # автомат ждал бы триггера, который не придёт. Взводится здесь,
                # а не в пути перехода, потому что перехода при старте нет.
                self._schedule_restored_timeout(definition, saved_state, restored_age)
            else:
                logger.warning(
                    f"Saved state '{saved_state}' for entity {definition.entity_id} is invalid, "
                    f"using initial state '{definition.initial_state}'"
                )
                self._states[definition.entity_id] = State(
                    current_state=definition.initial_state,
                    entered_at=loop_time(),
                    context={},
                )
        elif definition.entity_id not in self._states:
            entered_at = loop_time()
            self._states[definition.entity_id] = State(
                current_state=definition.initial_state,
                entered_at=entered_at,
                context={},
            )
            logger.debug(
                f"Registered FSM for entity {definition.entity_id} with initial state '{definition.initial_state}'"
            )

    def register_guard(self, name: str, guard_fn: Callable[..., bool]) -> None:
        """Register a guard condition function by name."""
        self._guards[name] = guard_fn
        logger.debug(f"Registered guard '{name}'")

    def register_action(self, name: str, action_fn: Callable[..., Any]) -> None:
        """Register an action function by name."""
        self._actions[name] = action_fn
        logger.debug(f"Registered action '{name}'")

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """
        Get all FSM entity IDs that belong to a specific device.

        FSM entity IDs follow the pattern: {device_id}_{template}_{priority}

        Args:
            device_id: The device ID to filter by.

        Returns:
            List of FSM entity IDs belonging to the device.

        Example:
             engine.get_entities_by_device("light.kitchen")
            ["light.kitchen_lighting_10", "light.kitchen_night_light_20"]

        Устройство берётся из ``target_device_id``, а не разбирается из
        идентификатора по префиксу: ``fan.base_smart`` — префикс
        ``fan.base_smart_2``, и поиск по ``startswith`` возвращал автоматы
        **другого** устройства. В бою (спека 014, 2026-10-12) датчик спальни
        маршрутизировался на оба рекуператора сразу. Префиксный путь остаётся
        запасным — для определений, собранных без ``target_device_id`` (тесты).
        """
        exact = [
            entity_id
            for entity_id, definition in self._definitions.items()
            if definition.target_device_id == device_id
        ]
        if exact:
            return exact
        return [
            entity_id
            for entity_id, definition in self._definitions.items()
            if definition.target_device_id is None and entity_id.startswith(f"{device_id}_")
        ]

    @property
    def event_bus(self) -> EventBus | None:
        """Шина событий платформы, в которую движок публикует свои события.

        Свойство публичное не для удобства: от его наличия зависит доставка
        событий Home Assistant подписчикам. Адаптер публикует `state_change` на
        эту шину (R-07 — одна шина на процесс), и пока у движка было только
        приватное `_event_bus`, проверка `hasattr(engine, "event_bus")` давала
        на настоящем движке `False`: адаптер уходил в запасную ветку с
        `engine.trigger()` по идентификатору сущности Home Assistant, который
        не является именем автомата. В бою это значило, что состояние
        устройства обновляла только ручная синхронизация, а каждое изменение
        состояния давало отказ `unknown_entity` (#9).

        Returns:
            Шина, с которой движок собран, либо `None`, если шины не было.
        """
        return self._event_bus

    def get_state(self, entity_id: str) -> State | None:
        """Get the current state of an entity."""
        return self._states.get(entity_id)

    def explain(self, entity_id: str) -> Decision | None:
        """Get the last decision made for an entity.

        Returns the most recent decision (outcome, reason, when), or None if
        the entity has never had a decision (never registered or never triggered).

        Args:
            entity_id: The entity to query.

        Returns:
            Decision record or None.
        """
        return self._decisions.get(entity_id)

    def _get_reason_text(self, reason_code: str) -> str:
        """Get human-readable text for a reason code.

        Falls back to the reason_code itself if not found in REASON_TEXT dictionary.

        Args:
            reason_code: The machine-readable reason code.

        Returns:
            Human-readable reason text.
        """
        return REASON_TEXT.get(reason_code, reason_code)

    def _record_decision(
        self,
        entity_id: str,
        outcome: str,
        reason_code: str | None,
        reason_text: str | None,
        trigger: str | None,
    ) -> None:
        """Record a decision (transition or rejection).

        Args:
            entity_id: The entity making the decision.
            outcome: 'on', 'off', 'none', or 'denied'.
            reason_code: Machine-readable reason code (from GUARD_DENIAL_REASONS or action name).
            reason_text: Human-readable reason (if None, determined from reason_code).
            trigger: The event that triggered this decision.
        """
        if reason_text is None and reason_code is not None:
            reason_text = self._get_reason_text(reason_code)
        if reason_text is None:
            reason_text = "неизвестно"

        decision = Decision(
            at=time.time(),
            outcome=outcome,
            reason_code=reason_code,
            reason_text=reason_text,
            trigger=trigger,
        )
        self._decisions[entity_id] = decision

    def get_all_states(self) -> dict[str, State]:
        """Get all current states of all entities."""
        return dict(self._states)

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Автоматы, в описаниях которых есть переход по этому событию.

        Нужно суточному циклу: он знает время («в 23:00 пора гасить»), но не
        знает, какие устройства вообще умеют гаситься по часам. Событие,
        которого нет ни в одном описании, отправлялось бы всем автоматам подряд
        и порождало отказ «нет такого перехода» у каждого, кто гасить не
        умеет — то есть шум в журнале и счётчике отказов вместо тишины.

        Args:
            trigger: Имя события.

        Returns:
            Идентификаторы автоматов с таким переходом.
        """
        return [
            entity_id
            for entity_id, definition in self._definitions.items()
            if any(transition.trigger == trigger for transition in definition.transitions)
        ]

    def device_id_of(self, entity_id: str) -> str | None:
        """Получить устройство автомата по его описанию.

        Устройство берётся из ``target_device_id``, а не разбирается из
        идентификатора: идентификатор строится как
        ``{устройство}_{шаблон}_{приоритет}``, и имя шаблона может содержать
        подчёркивание (``humidity_ventilation``), из-за чего разбор справа
        относит часть имени устройства к шаблону.

        Только чтение: правила переходов не затрагиваются (конституция I).

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Идентификатор устройства либо ``None``, если автомат не зарегистрирован.
        """
        definition = self._definitions.get(entity_id)
        return definition.target_device_id if definition is not None else None

    def expected_timeout_sec(self, entity_id: str) -> float | None:
        """Получить допустимое время пребывания автомата в текущем состоянии.

        Значение выводится из описания автомата: движок взводит таймер при
        переходе с ``timeout_sec``, поэтому «правильное» время ожидания уже
        описано, и ручной порог в конфигурации был бы вторым источником
        правды, способным с ним разойтись.

        Только чтение: правила переходов, дебаунс и механизм таймаутов не
        затрагиваются (конституция I).

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Максимум ``timeout_sec`` среди переходов, ведущих из текущего
            состояния; ``None``, если таких переходов нет, если состояние
            конечное или автомат не зарегистрирован. ``None`` означает, что
            состояние зависшим не считается: оно живёт, пока не придёт
            событие.
        """
        state = self._states.get(entity_id)
        if state is None:
            return None
        return self.expected_timeout_sec_in_state(entity_id, state.current_state)

    def expected_timeout_sec_in_state(self, entity_id: str, state: str) -> float | None:
        """То же вычисление, но для указанного состояния, а не текущего.

        Вынесено отдельно, чтобы взвод таймера и чтение ожидания сторожом
        считались по одному правилу. Иначе они могут разойтись: движок ждёт
        своего, сторож — своего, и расхождение выглядит как «сторож врёт».

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.

        Returns:
            Максимум ``timeout_sec`` среди переходов из состояния либо None.
        """
        definition = self._definitions.get(entity_id)
        if definition is None:
            return None

        timeouts = [
            transition.timeout_sec
            for transition in definition.transitions
            if transition.from_state == state
            and transition.timeout_sec is not None
            and transition.timeout_sec > 0
        ]
        return max(timeouts) if timeouts else None

    def reset_state(self, entity_id: str, state: str) -> None:
        """Reset the state of an entity to a specific state.

        Args:
            entity_id: ID of the entity to reset.
            state: The state to reset to.
        """
        if entity_id in self._states:
            self._states[entity_id] = State(
                current_state=state,
                entered_at=loop_time(),
                context={},
            )
            logger.debug(f"Reset state for entity {entity_id} to '{state}'")
        # Сброс состояния не является переходом, поэтому время последнего перехода
        # намеренно не обновляется: `since` показывает момент реального перехода.

    async def _cancel_timers(self, entity_id: str, log: Any | None = None) -> None:
        """Cancel any pending timers for an entity.

        Текущая задача не отменяется. Обработчик таймаута сам зовёт `trigger`,
        а тот на выполненном переходе отменяет прежние таймеры — включая тот,
        который его и вызвал. Без этого таймер отменял сам себя на середине
        срабатывания: переход начинал выполняться и обрывался, состояние
        оставалось прежним (найдено на стенде 2026-10-07, отложенный переход
        не наступал никогда).

        Args:
            entity_id: ID of the entity whose timers should be cancelled.
            log: Optional logger instance with trace_id bound.
        """
        if log is None:
            log = logger
        if entity_id in self._timers:
            timer_task = self._timers[entity_id]
            # Порядок обязателен: запись снимается ДО отмены. Иначе обработчик,
            # добравшись до конца перехода, запишет новый таймер — и следующая
            # отмена снимет уже не тот.
            del self._timers[entity_id]
            if timer_task is not asyncio.current_task() and not timer_task.done():
                timer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await timer_task
            log.debug(f"Cancelled timers for entity {entity_id}")

    def _guard_rejection_reason(
        self,
        guard: str | Callable[..., bool] | None,
        entity_id: str,
        context: dict[str, Any],
    ) -> str | None:
        """Определить причину отказа по условию, не вызывая само условие.

        Наличие данных проверяется **до** вызова условия, иначе пришлось бы
        разбирать результат условия, а это изменило бы контракт всех условий и
        затронуло работающий код. Отсутствие данных — не «значение не
        подходит», а отдельная причина: по ней видно, что молчит датчик, а не
        что состояние штатное.

        Args:
            guard: Имя условия либо сама функция.
            entity_id: Идентификатор автомата.
            context: Контекст перехода.

        Returns:
            `None`, если данные на месте; иначе причина отказа.
        """
        if guard is None:
            return None

        guard_fn = self._guards.get(guard) if isinstance(guard, str) else guard
        if guard_fn is None:
            return REASON_GUARD_FAILED

        required = getattr(guard_fn, "requires", ())
        # Нечитаемое значение — тоже отсутствие данных. Контракт наблюдаемых
        # сигналов различает «датчик молчит или значение нечитаемо» (проблема
        # данных) и «значение не подходит» (штатная работа), а `unavailable`
        # раньше попадал во второе: молчащий датчик выглядел как исправно
        # работающая вентиляция, у которой «просто не набралось влажности».
        # Проверка числовая, а не сравнение с None: иначе отказ получает чужое
        # имя, и оператору остаётся гадать, где искать.
        missing = [key for key in required if not _is_measurement(context.get(key))]
        if missing:
            logger.debug(
                f"Entity {entity_id}: guard {getattr(guard_fn, '__name__', guard)} "
                f"denied — no data for {', '.join(missing)}"
            )
            return REASON_GUARD_DATA_MISSING

        return None

    def _evaluate_guard(
        self,
        guard: str | Callable[..., bool] | None,
        entity_id: str,
        context: dict[str, Any],
        log: Any | None = None,
    ) -> bool:
        """Evaluate a guard condition. Passes both State and external context."""
        if log is None:
            log = logger

        if guard is None:
            return True

        guard_fn = self._guards.get(guard) if isinstance(guard, str) else guard
        if guard_fn is None:
            log.error(f"Guard '{guard}' not found in registry, denying transition")
            return False

        state = self._states.get(entity_id)
        try:
            # ПЕРЕДАЕМ ОБА АРГУМЕНТА: state и context
            result = guard_fn(state, context)
            name = guard_fn.__name__ if hasattr(guard_fn, "__name__") else str(guard_fn)
            log.debug(f"Guard '{name}' evaluated to {result}")
            return bool(result)
        except Exception as e:
            name = guard_fn.__name__ if hasattr(guard_fn, "__name__") else str(guard_fn)
            log.error(f"Guard '{name}' raised exception: {e}, denying transition")
            return False

    @staticmethod
    def _guard_denial_reason(
        guard: str | Callable[..., bool] | None,
        state: Any,
        context: dict[str, Any],
    ) -> str | None:
        """Имя причины, которым условие само называет свой отказ.

        Условие остаётся функцией «да/нет»: поднимать из него исключение или
        менять контракт значило бы тронуть все существующие условия. Вместо
        этого условие может объявить помощника ``deny_reason`` — функцию
        ``(state, context) -> str | None``. Возвращается только причина из
        ограниченного словаря: показатели не должны набирать произвольные
        метки из текста шаблонов.

        Args:
            guard: Имя условия либо сама функция.
            state: Текущее состояние автомата.
            context: Контекст перехода.

        Returns:
            Имя причины либо None.
        """
        guard_fn = guard if callable(guard) else None
        explain = getattr(guard_fn, "deny_reason", None)
        if explain is None:
            return None
        try:
            reason = explain(state, context)
        except Exception as exc:  # noqa: BLE001 — объяснение не должно ломать отказ
            logger.debug(f"Условие не смогло назвать причину отказа: {exc}")
            return None
        return reason if reason in GUARD_DENIAL_REASONS else None

    async def _execute_action(
        self,
        action: str | Callable[..., Any] | None,
        entity_id: str,
        context: dict[str, Any],
        log: Any | None = None,
    ) -> dict[str, Any]:
        """Execute an action. Returns a context patch to update the State immutably.

        If the action returns a CommandIntent and a dispatcher is available,
        the intent is submitted to the dispatcher for execution.
        """
        if log is None:
            log = logger

        if action is None:
            return {}

        action_fn = self._actions.get(action) if isinstance(action, str) else action
        if action_fn is None:
            log.error(f"Action '{action}' not found in registry")
            return {}

        state = self._states.get(entity_id)
        try:
            # enrich context with target_device_id and params from FSM definition
            enriched_context = self._enrich_context_for_action(entity_id, context)

            # ПЕРЕДАЕМ ОБА АРГУМЕНТА: state и enriched_context
            result = action_fn(state, enriched_context)
            if asyncio.iscoroutine(result):
                result = await result

            # Если action возвращает CommandIntent и есть dispatcher - отправляем его
            from core.commands.dispatcher import CommandIntent

            # Список шагов — команда с порядком: обогреватель принимает таймер
            # только после включения (живая проверка 2026-10-11), а выключается
            # только после обнуления таймера. Одно намерение такой порядок
            # выразить не может, поэтому шаги отправляются подряд и по порядку.
            intents: list[CommandIntent] | None = None
            if isinstance(result, CommandIntent):
                intents = [result]
            elif isinstance(result, list) and all(isinstance(i, CommandIntent) for i in result):
                intents = list(result)

            if intents is not None:
                if self._dispatcher is None:
                    log.warning(
                        f"No dispatcher available, skipping {len(intents)} CommandIntent(s): {result}"
                    )
                    return {}
                for index, intent in enumerate(intents):
                    log.debug(f"Submitting CommandIntent {index + 1}/{len(intents)}: {intent}")
                    sent = await self._dispatcher.submit(intent)
                    if not sent:
                        # Дальше идти нельзя: шаг с таймером без включённого
                        # прибора Home Assistant запишет без ошибки, а греть
                        # никто не будет — отказ будет выглядеть как успех.
                        log.warning(
                            f"Command step {index + 1}/{len(intents)} not sent "
                            f"({intent.source} → {intent.device_id}); remaining steps skipped"
                        )
                        return {}
                return {}

            # Если action возвращает dict, считаем это патчем для обновления контекста
            # (для обратной совместимости)
            context_patch = result if isinstance(result, dict) else {}

            name = action_fn.__name__ if hasattr(action_fn, "__name__") else str(action_fn)
            log.debug(f"Action '{name}' executed successfully, context patch: {context_patch}")
            return context_patch
        except Exception as e:
            name = action_fn.__name__ if hasattr(action_fn, "__name__") else str(action_fn)
            log.error(f"Action '{name}' raised exception: {e}")
            return {}

    def sanitise_for_merge(self, context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Вычистить устаревшие параметры из контекста перед мержем.

        Args:
            context: Накопленный контекст состояния.
            params: Параметры поведения из манифеста.

        Returns:
            Очищенный контекст.
        """
        return sanitise_stale_params(context, params)

    def _definition_params(self, entity_id: str) -> dict[str, Any]:
        """Параметры поведения автомата.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Параметры из описания автомата либо пустой словарь.
        """
        definition = self._definitions.get(entity_id)
        if definition is None or not definition.params:
            return {}
        return dict(definition.params)

    def _enrich_context_for_action(self, entity_id: str, context: dict[str, Any]) -> dict[str, Any]:
        """Enrich context with target_device_id and params from FSM definition.

        This ensures action handlers receive the real device ID (e.g., light.kitchen)
        instead of the internal FSM entity_id (e.g., light.kitchen__night_light_20).
        Also adds dispatcher to context so actions can call release().

        Args:
            entity_id: The internal FSM entity_id.
            context: The original context dictionary.

        Returns:
            dict: Enriched context with target_device_id, params, and dispatcher.
        """
        enriched = {**context}

        definition = self._definitions.get(entity_id)
        if definition is not None:
            # Add target_device_id as entity_id for action handlers
            if definition.target_device_id is not None:
                enriched["entity_id"] = definition.target_device_id
                enriched["target_device_id"] = definition.target_device_id
            # Add params from FSM definition
            if definition.params:
                enriched["params"] = definition.params

        # Add dispatcher to context so actions can call release()
        if self._dispatcher is not None:
            enriched["dispatcher"] = self._dispatcher

        return enriched

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        respect_debounce: bool = True,
        trace_id: str | None = None,
    ) -> bool:
        """
        Trigger an event for an entity's FSM.

        ``respect_debounce`` снимается событиями, которые приходят не от датчика:
        суточным расписанием и ручными командами. Дебаунс существует ради
        дребезга датчиков, а «погасить весь свет в 23:00» он превращал в
        «свет не погас»: событие, пришедшее сразу после движения, отбрасывалось.

        Args:
            entity_id: The entity identifier.
            event: The event name to trigger.
            external_ctx: Optional external context to merge with internal context.
            trace_id: Optional trace ID for logging correlation. If not provided,
                      generates a short UUID.

        Returns:
            True if a transition occurred, False otherwise.
        """
        # Generate or use provided trace_id
        if trace_id is None:
            trace_id = str(uuid.uuid4())[:8]

        # Bind trace_id to logger for this trigger
        log = logger.bind(trace_id=trace_id)

        # Таймер НЕ отменяется здесь, до разбора события.
        #
        # Отмена означает «состояние изменилось, прежнее ожидание больше не
        # действует». Но событие может не дать перехода вовсе: в `lighting.yaml`
        # нет перехода по триггеру `motion_cleared`, и датчик движения в жилой
        # комнате шлёт события каждые 15–60 с. Прежняя отмена стояла первым
        # действием, поэтому каждое такое событие съедало таймер, а новый не
        # взводилось — перехода не было. Отложенный переход не наступал никогда,
        # и свет не гас никогда, в том числе в живом процессе без перезапуска
        # (найдено на стенде 2026-10-07).
        #
        # Настоящий переход отменяет прежний таймер ниже, в ветке выполненного
        # перехода: там состояние действительно меняется.
        if entity_id not in self._definitions:
            self._record_rejection(entity_id, event, REASON_UNKNOWN_ENTITY)
            self._publish_rejection(entity_id, event, None, REASON_UNKNOWN_ENTITY, trace_id)
            return False

        definition = self._definitions[entity_id]

        if entity_id not in self._states:
            log.error(f"No state found for entity {entity_id}")
            self._record_rejection(entity_id, event, REASON_NO_STATE)
            self._publish_rejection(entity_id, event, None, REASON_NO_STATE, trace_id)
            return False

        current_state = self._states[entity_id]
        now = asyncio.get_event_loop().time()

        # Check debounce. События вне датчиков (расписание суток, ручные команды)
        # отсечкой не отбрасываются: иначе расписание, наступившее сразу после
        # движения, молча пропадало бы, и свет горел бы до утра.
        if respect_debounce and entity_id in self._last_transition_time:
            elapsed = now - self._last_transition_time[entity_id]
            if elapsed < definition.debounce_sec:
                log.debug(
                    f"Entity {entity_id}: Debounce active ({elapsed:.3f}s < {definition.debounce_sec}s), "
                    f"ignoring event '{event}'"
                )
                self._record_rejection(entity_id, event, REASON_DEBOUNCED)
                self._publish_rejection(
                    entity_id, event, current_state.current_state, REASON_DEBOUNCED, trace_id
                )
                return False

        # Find matching transitions
        matching_transitions = [
            t
            for t in definition.transitions
            if t.from_state == current_state.current_state and t.trigger == event
        ]

        if not matching_transitions:
            log.debug(
                f"Entity {entity_id}: No transitions for event '{event}' from state '{current_state.current_state}'"
            )
            self._record_rejection(entity_id, event, REASON_NO_TRANSITION)
            self._publish_rejection(
                entity_id, event, current_state.current_state, REASON_NO_TRANSITION, trace_id
            )
            return False

        # Merge contexts
        merged_context = sanitise_stale_params(
            current_state.context, self._definition_params(entity_id)
        )
        # Параметры поведения видны и условиям, а не только действиям. Раньше
        # они доезжали только до действий (`_enrich_context_for_action`), и
        # условие читало зашитое в своё имя значение: у `humidity_above_60`
        # порог 60 перебивал `humidity_threshold` из манифеста, то есть
        # настройка порога вентиляции не имела силы (Known Issue #67).
        merged_context.update(self._definition_params(entity_id))
        definition_room = self._definitions.get(entity_id)
        if definition_room is not None and definition_room.room:
            merged_context.setdefault("room", definition_room.room)
        # Устройство автомата — тоже в контекст, и по той же причине, что и
        # параметры поведения: условие блокировки (`is_manual_override_enabled`)
        # ищет, к какому устройству относится ручное действие, и без этого поля
        # видела пустой контекст и запрещала переход на защите от локаута.
        # Раньше это поле доезжало только до действий.
        if definition_room is not None and definition_room.target_device_id:
            merged_context.setdefault("target_device_id", definition_room.target_device_id)
        # События суточного расписания — правило безопасности, а не удобство
        # автоматики: выключение по часам обязано обойти блокировку человека.
        # Иначе «не горит всю ночь» нарушается ровно в те вечера, когда человек
        # вмешивался в свет (проверено в боре 2026-10-09).
        if event in SAFETY_EVENTS:
            merged_context["bypass_lockout"] = True
        if external_ctx:
            merged_context.update(external_ctx)

        # Причины отказов по условиям: отсутствие данных и «значение не подходят»
        # неразличимы в счётчике, если не различать их здесь.
        guard_denials: dict[str, str] = {}

        # Process transitions (first valid one wins)
        for transition in matching_transitions:
            # Отсутствие данных проверяется до вызова условия: условие остаётся
            # функцией «да/нет», а отказ получает собственное имя.
            missing = self._guard_rejection_reason(transition.guard, entity_id, merged_context)
            if missing is None and not self._evaluate_guard(
                transition.guard, entity_id, merged_context, log
            ):
                # Условие может назвать причину сама (`may_turn_on` знает, что
                # отказало из-за ночного окна), но словарь причин ограничен:
                # неизвестное имя не должно плодить метки в показателях.
                missing = (
                    self._guard_denial_reason(transition.guard, current_state, merged_context)
                    or REASON_GUARD_FAILED
                )

            if missing is not None:
                guard_denials.setdefault(missing, str(transition.guard))
                if _is_diagnostic_entity(entity_id):
                    # Климат и вентиляция разбираются утром по журналу: отказ
                    # пишется на КАЖДОМ событии с входом, из которого он вырос.
                    log.warning(
                        f"[ДИАГНОСТИКА] {entity_id}: '{current_state.current_state}' → "
                        f"'{transition.to_state}' по '{event}' — условие "
                        f"{transition.guard}: ОТКАЗ ({missing}); вход: "
                        f"{_diagnostic_context(merged_context)}"
                    )
                log.debug(
                    f"Entity {entity_id}: Guard '{transition.guard}' failed for transition "
                    f"'{current_state.current_state}' -> '{transition.to_state}' ({missing})"
                )
                continue

            if _is_diagnostic_entity(entity_id):
                log.warning(
                    f"[ДИАГНОСТИКА] {entity_id}: '{current_state.current_state}' → "
                    f"'{transition.to_state}' по '{event}' — условие "
                    f"{transition.guard}: РАЗРЕШЕНО; действие {transition.action}; вход: "
                    f"{_diagnostic_context(merged_context)}"
                )

            # Execute action
            context_patch = await self._execute_action(
                transition.action, entity_id, merged_context, log
            )

            new_context = {**merged_context, **context_patch}

            # Таймер прежнего состояния снимается здесь — то есть на
            # выполненном переходе, а не на каждом событии. Отмена означает
            # «ожидание прежнего состояния больше не действует», и только
            # сменившееся состояние делает его недействующим.
            await self._cancel_timers(entity_id, log)

            # Create new state
            new_state = State(
                current_state=transition.to_state, entered_at=now, context=new_context
            )

            # Update state
            self._states[entity_id] = new_state
            self._last_transition_time[entity_id] = now
            self.note_transition(entity_id)

            # Persist state if persistence is enabled.
            # Асинхронный путь обязателен: save_state делает fsync, и вызов
            # прямо из корутины перехода останавливал event loop на время
            # записи — при нескольких автоматах это складывалось в задержки
            # на WebSocket и срабатывания сторожа.
            #
            # `entered_at` передаётся настенным временем: по нему после
            # перезапуска восстанавливается остаток отложенного перехода. Без
            # него состояние восстанавливалось, а таймер нет (Known Issue #78).
            if self._persistence is not None:
                wall_entered_at = time.time()
                saver = getattr(self._persistence, "save_state_async", None)
                if saver is not None:
                    await saver(entity_id, transition.to_state, new_context, wall_entered_at)
                else:
                    self._persistence.save_state(
                        entity_id, transition.to_state, new_context, wall_entered_at
                    )

            log.info(
                f"Entity {entity_id}: Transition '{current_state.current_state}' -> '{transition.to_state}' "
                f"triggered by '{event}'"
                + (f" (guard: {transition.guard})" if transition.guard else "")
                + (f" (action: {transition.action})" if transition.action else "")
            )

            # Record the decision (T005, FR-005)
            action_name = transition.action if isinstance(transition.action, str) else None
            outcome = "none"
            reason_code = None
            if action_name:
                # Determine on/off from action name (T007)
                if "_off" in action_name.lower():
                    outcome = "off"
                    reason_code = "action_off"
                elif "_on" in action_name.lower() or action_name.lower().startswith("turn_on"):
                    outcome = "on"
                    reason_code = "action_on"
                else:
                    outcome = "on"  # Assume on for unknown actions
                    reason_code = "action"
            self._record_decision(
                entity_id=entity_id,
                outcome=outcome,
                reason_code=reason_code,
                reason_text=None,  # Will be determined
                trigger=event,
            )

            # Publish after the new state is written, so a subscriber reading the
            # engine always observes the state the event announces (R-02).
            self._publish_transition(
                entity_id, event, current_state.current_state, transition.to_state, trace_id
            )

            # Таймер взводится по новому состоянию, а не по сработавшему
            # переходу: `timeout_sec` означает «сколько можно находиться в
            # состоянии», и шаблоны объявляют его на исходящем переходе
            # (`lighting.yaml`: ON_MOTION --[timeout]--> OFF, 30 с). Прежний
            # код смотрел на сработавший переход, где таймера нет, поэтому
            # таймауты не срабатывали никогда, а `expected_timeout_sec` видел
            # ожидание, которого движок не выполнял (Known Issue #66).
            #
            # Таймер прежнего состояния снимается: состояние сменилось, его
            # ожидание больше не действует. `timeout_sec` сработавшего перехода
            # учитывается тоже — иначе сломалась бы форма объявления «таймер на
            # входящем переходе», на которой написаны существующие тесты.
            declared = [
                value
                for value in (
                    self._incoming_timeout(definition, transition),
                    self._outgoing_timeout(entity_id, transition.to_state),
                )
                if value is not None
            ]
            timeout_sec = max(declared) if declared else None
            if timeout_sec is not None:
                self._timers[entity_id] = asyncio.create_task(
                    self._timeout_handler(entity_id, timeout_sec, trace_id)
                )
                log.debug(
                    f"Entity {entity_id}: Scheduled timeout transition in {timeout_sec}s "
                    f"for state '{transition.to_state}'"
                )

            return True

        log.debug(f"Entity {entity_id}: No valid transitions for event '{event}'")
        # Причина отказа выбирается по тому, чего не хватило: отсутствие данных
        # и неподходящее значение — разные ситуации, и оператор должен видеть
        # какую именно. Если отказов не было (все переходы прошли), причина
        # прежняя.
        # Причина выбирается из названных самими условиями: отсутствие данных
        # важнее прочих (это поломка данных, а не штатная работа), дальше —
        # названная причина вроде ночного окна, и только потом общее
        # «условие не прошло». Раньше список понимал только первые два, и
        # ночной отказ приходил как безликое `guard_failed`.
        if REASON_GUARD_DATA_MISSING in guard_denials:
            reason = REASON_GUARD_DATA_MISSING
        else:
            named = next((name for name in guard_denials if name in GUARD_DENIAL_REASONS), None)
            reason = named or REASON_GUARD_FAILED
        self._record_rejection(entity_id, event, reason)
        self._publish_rejection(entity_id, event, current_state.current_state, reason, trace_id)
        return False

    def _restored_state_age(self, entity_id: str) -> float:
        """Сколько секунд восстановленное состояние уже пролежало.

        Время входа хранится настенным (`time.time()`), потому что монотонные
        часы цикла после перезапуска бессмысленны: они отсчитываются заново от
        старта процесса и ничего не говорят о том, сколько автомат пролежал в
        состоянии до остановки.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Возраст состояния в секундах; 0.0, если время входа не сохранено
            (состояния, записанные прежней версией платформы).
        """
        if self._persistence is None:
            return 0.0

        loader = getattr(self._persistence, "load_state_entry", None)
        if loader is None:
            return 0.0

        entry = loader(entity_id) or {}
        entered_at = entry.get("entered_at")
        if not isinstance(entered_at, (int, float)) or entered_at <= 0:
            return 0.0

        age = time.time() - float(entered_at)
        # Метка из будущего означает рассинхронизацию часов, а не состояние,
        # которое пролежало отрицательное время.
        return max(0.0, age)

    def _schedule_restored_timeout(self, definition: FSMDefinition, state: str, age: float) -> None:
        """Взвести отложенный переход для восстановленного состояния.

        Остаток считается от фактического времени в состояние, а не от старта
        контейнера. Иначе перезапуск продлевал бы свечение: состояние, пролежав
        25 с из 30, получало бы ещё 30 вместо оставшихся 5, и с каждым
        перезапуском расхождение росло бы.

        Args:
            definition: Определение автомата.
            state: Восстановленное имя состояния.
            age: Сколько секунд состояние уже пролежало, сек.
        """
        timeout_sec = self._outgoing_timeout(definition.entity_id, state)
        if timeout_sec is None:
            return

        remaining = max(0.0, timeout_sec - age)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Без работающего цикла таймер взвести нечем: задачу создать негде.
            # Сборка контейнера в тестах проходит без цикла, и это не должно
            # быть отказом регистрации автомата (ср. FR-016).
            logger.warning(
                f"Entity {definition.entity_id}: restored state '{state}' has a "
                f"{timeout_sec}s timeout, but no running event loop — timer not armed"
            )
            return

        self._timers[definition.entity_id] = asyncio.create_task(
            self._timeout_handler(definition.entity_id, remaining, "restored")
        )
        logger.warning(
            f"Entity {definition.entity_id}: restored state '{state}', timer armed for "
            f"{remaining:.1f}s of {timeout_sec:.1f}s (state held for {age:.1f}s)"
        )

    @staticmethod
    def _incoming_timeout(definition: FSMDefinition, transition: Transition) -> float | None:
        """Возвращает ``timeout_sec`` сработавшего перехода, если он задан.

        Args:
            definition: Описание автомата.
            transition: Сработавший переход.

        Returns:
            Время ожидания или None.
        """
        value = transition.timeout_sec
        if value is not None and value > 0:
            return value
        return None

    def _outgoing_timeout(self, entity_id: str, state: str) -> float | None:
        """Возвращает ожидание по исходящим переходам по триггеру ``timeout``.

        Фильтр по триггеру обязателен. Шаблоны объявляют ожидание так:
        ``ON_MOTION --[timeout]--> OFF, timeout_sec=30`` — то есть на том самом
        переходе, который таймер и должен вызвать. Но встречается и форма
        ``OFF --[manual_override]--> ON_MANUAL, timeout_sec=3600``, где тот же
        параметр описывает уже достигнутое состояние, а из ``OFF`` события
        ``timeout`` никто не слушает. Взводить таймер по таким переходам нельзя:
        он истечёт вхолостую.

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.

        Returns:
            Время ожидания либо None, если из состояния нечему ждать.
        """
        definition = self._definitions.get(entity_id)
        if definition is None:
            return None

        timeouts = [
            transition.timeout_sec
            for transition in definition.transitions
            if transition.from_state == state
            and transition.trigger == "timeout"
            and transition.timeout_sec is not None
            and transition.timeout_sec > 0
        ]
        return max(timeouts) if timeouts else None

    async def _timeout_handler(self, entity_id: str, timeout_sec: float, trace_id: str) -> None:
        """Handle timeout-based transitions.

        Args:
            entity_id: ID of the entity whose timeout is being handled.
            timeout_sec: Timeout duration in seconds.
            trace_id: Trace ID for logging correlation.
        """
        log = logger.bind(trace_id=trace_id)
        try:
            await asyncio.sleep(timeout_sec)
            log.debug(f"Entity {entity_id}: Timeout expired, triggering 'timeout' event")
            await self.trigger(entity_id, "timeout", trace_id=trace_id)
        except asyncio.CancelledError:
            log.debug(f"Entity {entity_id}: Timeout cancelled")
            raise

    def unregister(self, entity_id: str) -> None:
        """Unregister an FSM, removing it from internal state and cancelling all timers.

        Args:
            entity_id: ID of the entity to unregister.
        """
        # Cancel any pending timers for this entity
        if entity_id in self._timers:
            timer_task = self._timers[entity_id]
            if not timer_task.done():
                timer_task.cancel()
                # In synchronous context, we can't await, so just cancel
                with contextlib.suppress(asyncio.CancelledError):
                    pass
            del self._timers[entity_id]
            logger.debug(f"Cancelled timers for entity {entity_id} during unregister")

        # Remove from states dictionary
        if entity_id in self._states:
            del self._states[entity_id]
            logger.debug(f"Removed state for entity {entity_id}")

        # Remove from definitions dictionary
        if entity_id in self._definitions:
            del self._definitions[entity_id]
            logger.debug(f"Removed definition for entity {entity_id}")

        # Clean up other tracking dictionaries
        if entity_id in self._last_transition_time:
            del self._last_transition_time[entity_id]
        self._last_transition_wall.pop(entity_id, None)

        logger.info(f"Unregistered FSM for entity {entity_id}")

    async def _drain_publish_tasks(self) -> None:
        """Дождаться или отменить задачи публикации событий (FR-012)."""
        tasks = list(self._publish_tasks)
        if not tasks:
            return

        done, pending = await asyncio.wait(tasks, timeout=PUBLISH_DRAIN_TIMEOUT_SEC)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.debug(f"Drained {len(done)} publish tasks, cancelled {len(pending)}")

    async def shutdown(self) -> None:
        """Shutdown the engine, cancelling all pending timers."""
        for entity_id in list(self._timers.keys()):
            await self._cancel_timers(entity_id)
        await self._drain_publish_tasks()
        logger.info("FSM Engine shutdown complete")
