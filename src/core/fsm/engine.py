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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.fsm.actions import ActionMixin
from core.fsm.decisions import DecisionMixin
from core.fsm.guards import GuardMixin
from core.fsm.models import (
    Decision,
    FSMDefinition as FSMDefinition,
    State as State,
    Transition as Transition,
)
from core.fsm.publishing import (
    PUBLISH_DRAIN_TIMEOUT_SEC as PUBLISH_DRAIN_TIMEOUT_SEC,
    PublishingMixin,
)
from core.fsm.timers import TimerMixin
from core.fsm.transitions import (
    KNOWN_BEHAVIOR_PARAM_KEYS as KNOWN_BEHAVIOR_PARAM_KEYS,
    SAFETY_EVENTS as SAFETY_EVENTS,
    TransitionMixin,
    _diagnostic_context as _diagnostic_context,
    _is_diagnostic_entity as _is_diagnostic_entity,
    sanitise_stale_params as sanitise_stale_params,
)


if TYPE_CHECKING:
    from core.commands.dispatcher import CommandDispatcher
    from core.events.event_bus import EventBus
    from core.persistence.state_persistence import StatePersistence


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


class FSMEngine(
    TimerMixin, PublishingMixin, DecisionMixin, GuardMixin, ActionMixin, TransitionMixin
):
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
        self._rejection_counts: dict[
            str, int
        ] = {}  # Сущности, об отказе по которым уже сказано в журнале. Отказ честный —
        # сущности действительно нет в манифесте, — но повторять его тысячи раз
        # незачем: в доме синхронизировано 1489 устройств против 6 в манифесте,
        # и это давало две строки журнала на каждое изменение состояния, то есть
        # 80% объёма. Число строк растёт с числом РАЗЛИЧНЫХ сущностей, а не с
        # числом событий.
        self._reported_rejections: set[tuple[str, str]] = set()
        # Пары (автомат, событие), о «нет подходящего перехода» по которым в
        # журнал уже сказано. Повторы остаются в счётчике отказов, а не в
        # журнале: 389 таких записей за сутки делали утренний разбор дороже, чем
        # он должен быть, хотя каждая из них означает «повода не было» (B65).
        self._published_noops: set[tuple[str, str]] = set()
        # Повторные отказы по одной и той же причине: журнал хранит **события**, а
        # не поток. Одинаковый отказ (автомат, событие, причина) пишется раз в
        # `REFUSAL_REPEAT_WINDOW_SEC`, объём остаётся в `rejection_counts()`.
        # Иначе ночник, отказывающий днём, и вентилятор, решающий «в санузле
        # комфортно», давали около 1400 записей в сутки (B67).
        self._published_refusals: dict[tuple[str, str, str], float] = {}
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
                self._schedule_restored_timeout(
                    definition, saved_state, restored_age, saved_context
                )
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
            Максимум ``timeout_sec`` среди переходов по триггеру ``timeout`` либо
            None.
        """
        definition = self._definitions.get(entity_id)
        if definition is None:
            return None

        # Условия переходов учитываются и здесь: у одного состояния может быть
        # несколько сроков, и какой из них действует, решает контекст состояния
        # (например, ручной свет при «мы спим» гаснет через 5 минут, а не через
        # час). Сторож обязан ждать столько же, сколько движок.
        current = self._states.get(entity_id)
        context = current.context if current is not None and current.current_state == state else {}

        # Только переход по триггеру `timeout` взводит таймер состояния. У
        # входных переходов `timeout_sec` — верхняя граница ожидания события, а
        # не срок жизни состояния. Без фильтра сторож считал `OFF` ночника
        # зависшим через 300 с после `sleep_started` (боевая находка 2026-10-26):
        # в снимке появлялся ложный `problem_count`.
        timeouts = [
            transition.timeout_sec
            for transition in definition.transitions
            if transition.from_state == state
            and transition.trigger == "timeout"
            and transition.timeout_sec is not None
            and transition.timeout_sec > 0
            and (
                transition.guard is None
                or self._evaluate_guard(transition.guard, entity_id, context)
            )
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

    def sanitise_for_merge(self, context: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        """Вычистить устаревшие параметры из контекста перед мержем.

        Args:
            context: Накопленный контекст состояния.
            params: Параметры поведения из манифеста.

        Returns:
            Очищенный контекст.
        """
        return sanitise_stale_params(context, params)

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

    async def shutdown(self) -> None:
        """Shutdown the engine, cancelling all pending timers."""
        for entity_id in list(self._timers.keys()):
            await self._cancel_timers(entity_id)
        await self._drain_publish_tasks()
        logger.info("FSM Engine shutdown complete")
