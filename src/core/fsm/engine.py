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
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from core.events.fsm_events import (
    GUARD_DENIAL_REASONS,
    REASON_DEBOUNCED,
    REASON_GUARD_DATA_MISSING,
    REASON_GUARD_FAILED,
    REASON_NO_STATE,
    REASON_NO_TRANSITION,
    REASON_NOT_APPLICABLE,
    REASON_UNKNOWN_ENTITY,
)
from core.fsm.decisions import DecisionMixin
from core.fsm.models import (
    Decision,
    FSMDefinition as FSMDefinition,
    State as State,
    Transition as Transition,
    is_measurement,
)
from core.fsm.publishing import (
    PUBLISH_DRAIN_TIMEOUT_SEC as PUBLISH_DRAIN_TIMEOUT_SEC,
    PublishingMixin,
)
from core.fsm.timers import TimerMixin
from core.models.manifest import AutomationDomainRules


if TYPE_CHECKING:
    from core.commands.dispatcher import CommandDispatcher, CommandIntent
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

#: Движение: в комнатах без окон (`always_on_motion_rooms`) включение по нему не
#: отменяется ручной блокировкой — это тоже правило безопасности, а не удобство
#: (`.ai/04_RULES.md`, требование владельца 2026-10-15).
MOTION_EVENTS: frozenset[str] = frozenset({"motion_detected"})


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
        # Плановый свет (B111): команды шаблона обходят ручную блокировку.
        # Параметр добавлен в белый список, чтобы после удаления из манифеста
        # он не остался в сохранённом контексте и не обходил блокировку вечно.
        "bypass_lockout",
        "humidity_threshold",
        "motion_timeout_sec",
        "brightness",
        # Явные яркость и цвет при включении света (требование владельца
        # 2026-10-13, B48): иначе лампа вспоминает прошлые настройки.
        "brightness_pct",
        "color_temp_kelvin",
        # Глобальная цветовая температура (B97): лампа берёт текущее значение
        # дома, а перед выключением получает ночной режим, чтобы не вспыхнуть
        # прошлой яркой яркостью при следующем включении ночника.
        "use_global_color_temp",
        "prepare_for_night",
        # Вечерняя яркость без движения (B104): свет не гаснет, а тускнеет.
        "dim_when_idle",
        "dim_brightness_pct",
        # Кривая яркости света над кроватью (B114): от dim_from до dim_at
        # яркость идёт к dim_to_pct; читает служба световой температуры.
        "dim_from",
        "dim_at",
        "dim_start_pct",
        "dim_to_pct",
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
        # Шторы (спека 015): роль шторы (дверь/обычная) и признак «закрывать,
        # когда дома только собаки».
        "cover_role",
        "closes_when_dogs_only",
    }
    # Доменные правила дома фабрика превращает в параметры поведения (T012
    # спеки 014), значит и они попадают в контекст состояния.
    | frozenset(AutomationDomainRules.model_fields)
)


def _without_transient(context: dict[str, Any]) -> dict[str, Any]:
    """Контекст без одноразовых признаков — ключей с ведущим подчёркиванием.

    Событие может принести признак, нужный только этому пересмотру (например,
    ``_startup_reapply`` — первый пересмотр после запуска платформы). В
    накопленном контексте автомата такой признак жил бы дальше и менял бы
    поведение следующих переходов: в бою 2026-10-13 признак запуска всплыл на
    следующем тике сторожа вентиляции, и включение с процентом ушло повторно —
    то самое, что сбрасывает режим рекуператора. Одноразовые признаки видны
    условиям и действиям текущего перехода, но не сохраняются в состоянии.

    Args:
        context: Собранный контекст перехода (накопленный + внешний + правка).

    Returns:
        Копия контекста без ключей, начинающихся с ``_``.
    """
    return {key: value for key, value in context.items() if not key.startswith("_")}


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
    "cover_modes",
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
    # Шторы (спека 015): решение зависит только от этих флагов, и утренний
    # разбор должен их видеть, чтобы объяснить, почему штора открыта или закрыта.
    "covers_enabled",
    "my_doma",
    "sobaki_doma",
    "covers_close_night",
    "cover_emergency",
    "cover_role",
    "closes_when_dogs_only",
)


def _is_diagnostic_entity(entity_id: str) -> bool:
    """Относится ли автомат к климату, вентиляции или шторам.

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


def _turns_light_off(action: Any) -> bool:
    """Гасит ли действие свет.

    Нужно, чтобы условие включения света знало момент собственного выключения:
    движение сразу после него — эхо датчика, а не человек (2026-10-14).

    Args:
        action: Имя действия перехода либо сама функция.

    Returns:
        True, если действие гасит свет.
    """
    return isinstance(action, str) and action in LIGHT_OFF_ACTIONS


#: Действия, которые гасят свет. Перечислены явно, а не выведены из имени:
#: «выключение» для света — только эти два, и догадка по подстроке записала бы
#: сюда ещё и обогреватель.
LIGHT_OFF_ACTIONS: Final[frozenset[str]] = frozenset({"turn_off_light", "turn_off_night_light"})

#: Через сколько секунд повторять в журнале один и тот же отказ (автомат,
#: событие, причина). Час: утренний разбор видит почасовой ряд повторов, а объём
#: остаётся в `rejection_counts()`. Без этого ночник, отказывающий днём
#: (`modifier_off`), и вентилятор, решающий «в санузле комфортно», давали около
#: 1400 записей в сутки — журнал тонул в повторах (B67).
REFUSAL_REPEAT_WINDOW_SEC: Final[float] = 3600.0


class FSMEngine(TimerMixin, PublishingMixin, DecisionMixin):
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
        missing = [key for key in required if not is_measurement(context.get(key))]
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
                        if intent.best_effort:
                            # Вспомогательный шаг: без него основное действие
                            # всё равно нужно выполнить. Пример — обнуление
                            # таймера перед выключением обогревателя.
                            log.warning(
                                f"Command step {index + 1}/{len(intents)} not sent "
                                f"({intent.source} → {intent.device_id}); "
                                "continuing: step is best effort"
                            )
                            continue
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

    def definition_params(self, entity_id: str) -> dict[str, Any]:
        """Публично: параметры поведения автомата (из манифеста).

        Нужны тому, кто решает о поведении снаружи переходов — например, сверке
        вечернего света: она различает свет, гаснущий по отбою
        (``off_by: sleep``), и свет, живущий до рассвета (``off_by: sunrise``).

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Копия параметров либо пустой словарь.
        """
        return self._definition_params(entity_id)

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
        prepared = self._prepare_trigger(entity_id, event, respect_debounce, trace_id, log)
        if prepared is None:
            return False
        definition, current_state, now = prepared

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
            self._reject(
                entity_id, event, current_state.current_state, REASON_NO_TRANSITION, trace_id
            )
            return False

        merged_context = self._transition_context(entity_id, event, current_state, external_ctx)

        # Причины отказов по условиям: отсутствие данных и «значение не подходят»
        # неразличимы в счётчике, если не различать их здесь.
        guard_denials: dict[str, str] = {}
        # Сколько переходов оказалось неприменимо к прибору (у обогревателя нет
        # охлаждения). Нужно, чтобы «нет подходящего перехода» не превратилось в
        # отказ условия (B66).
        not_applicable = 0

        # Process transitions (first valid one wins)
        for transition in matching_transitions:
            missing = self._transition_denial(
                transition, entity_id, current_state, merged_context, log
            )

            if missing == REASON_NOT_APPLICABLE:
                # Переход к прибору не относится (у обогревателя нет охлаждения):
                # это не отказ решения, и в журнал, счётчик отказов и последнее
                # решение такое не пишется — иначе каждое показание температуры
                # давало бы «кондиционер запрещён» по обогревателю (B66, около
                # 720 записей в сутки).
                not_applicable += 1
                continue

            if missing is not None:
                guard_denials.setdefault(missing, str(transition.guard))
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
            # Момент нашего выключения света запоминается в контексте состояния.
            # Нужен условию включения: движение, пришедшее в первые секунды после
            # НАШЕГО выключения, — это реакция датчика (камеры) на смену
            # освещённости, а не человек; приняв его за человека, свет зажигается
            # снова и мигает (боевой случай 2026-10-14, фонари сада).
            #
            # Считается по факту команды, а не по входу в состояние «выключено»:
            # в него ведут и переходы без действия (расписание, «мы спим»), и по
            # ним окно эха не должно открываться.
            if _turns_light_off(transition.action):
                context_patch = {**context_patch, "light_off_at": time.time()}

            new_context = _without_transient({**merged_context, **context_patch})
            await self._commit_transition(
                entity_id=entity_id,
                definition=definition,
                event=event,
                current_state=current_state,
                transition=transition,
                new_context=new_context,
                now=now,
                trace_id=trace_id,
                log=log,
            )
            return True

        log.debug(f"Entity {entity_id}: No valid transitions for event '{event}'")
        reason = self._no_transition_reason(guard_denials, not_applicable)
        self._reject(entity_id, event, current_state.current_state, reason, trace_id)
        return False

    def _prepare_trigger(
        self,
        entity_id: str,
        event: str,
        respect_debounce: bool,
        trace_id: str,
        log: Any,
    ) -> tuple[FSMDefinition, State, float] | None:
        """Проверить, можно ли разбирать событие, и записать отказ, если нельзя.

        Здесь три причины «события сейчас нет»: автомат неизвестен, у автомата
        нет состояния и включена отсечка дребезга. Все они записываются и
        публикуются одинаково — через `_reject`.

        Args:
            entity_id: Идентификатор автомата.
            event: Имя события.
            respect_debounce: Учитывать ли отсечку дребезга.
            trace_id: Идентификатор трассировки.
            log: Журнал с привязанным trace_id.

        Returns:
            Определение, текущее состояние и момент времени; `None`, если
            события для этого автомата сейчас нет.
        """
        if entity_id not in self._definitions:
            self._reject(entity_id, event, None, REASON_UNKNOWN_ENTITY, trace_id)
            return None

        definition = self._definitions[entity_id]

        if entity_id not in self._states:
            log.error(f"No state found for entity {entity_id}")
            self._reject(entity_id, event, None, REASON_NO_STATE, trace_id)
            return None

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
                self._reject(
                    entity_id, event, current_state.current_state, REASON_DEBOUNCED, trace_id
                )
                return None

        return definition, current_state, now

    def _reject(
        self,
        entity_id: str,
        event: str,
        state: str | None,
        reason: str,
        trace_id: str,
    ) -> None:
        """Записать отказ в счётчики и опубликовать его.

        Args:
            entity_id: Идентификатор автомата.
            event: Имя события.
            state: Состояние на момент отказа (может быть неизвестно).
            reason: Причина отказа.
            trace_id: Идентификатор трассировки.

        Returns:
            Ничего.
        """
        self._record_rejection(entity_id, event, reason)
        self._publish_rejection(entity_id, event, state, reason, trace_id)

    def _transition_context(
        self,
        entity_id: str,
        event: str,
        current_state: State,
        external_ctx: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Собрать контекст перехода: состояние, параметры поведения, событие.

        Параметры поведения и устройство нужны не только действиям, но и
        условиям — см. комментарии ниже: без них условие читало зашитое в своё
        имя значение и не видело, к какому прибору относится ручное действие.

        Args:
            entity_id: Идентификатор автомата.
            event: Имя события.
            current_state: Текущее состояние автомата.
            external_ctx: Внешний контекст события (может быть пустым).

        Returns:
            Контекст перехода.
        """
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
        # Комнаты без окон (`always_on_motion_rooms`: санузел, контейнер) — там
        # свет по движению включается всегда: днём там так же темно, и другого
        # света нет. Поэтому ручная блокировка не отменяет включение по движению:
        # человек погасил свет и ушёл, а следующему он нужен. Иначе комната
        # молчит час после каждого ручного выключения (боевой разбор 2026-10-15:
        # свет в санузле не зажёгся по движению, потому что утром его погасили
        # сами).
        windowless_rooms = {
            str(item) for item in merged_context.get("always_on_motion_rooms") or ()
        }
        if event in MOTION_EVENTS and str(merged_context.get("room") or "") in windowless_rooms:
            merged_context["bypass_lockout"] = True
        if external_ctx:
            merged_context.update(external_ctx)
        return merged_context

    def _transition_denial(
        self,
        transition: Transition,
        entity_id: str,
        current_state: State,
        merged_context: dict[str, Any],
        log: Any,
    ) -> str | None:
        """Проверить условие перехода и назвать причину отказа.

        Отсутствие данных проверяется до вызова условия: условие остаётся
        функцией «да/нет», а отказ получает собственное имя.

        Args:
            transition: Проверяемый переход.
            entity_id: Идентификатор автомата.
            current_state: Текущее состояние автомата.
            merged_context: Контекст перехода.
            log: Журнал с привязанным trace_id.

        Returns:
            `None`, если переход разрешён; иначе причина отказа, в том числе
            `REASON_NOT_APPLICABLE` для переходов, не относящихся к прибору.
        """
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

        if missing is None or missing == REASON_NOT_APPLICABLE:
            return missing

        if _is_diagnostic_entity(entity_id):
            # Климат и вентиляция разбираются утром по журналу: отказ
            # пишется на КАЖДОМ событии с входом, из которого он вырос.
            log.warning(
                f"[ДИАГНОСТИКА] {entity_id}: '{current_state.current_state}' → "
                f"'{transition.to_state}' по '{transition.trigger}' — условие "
                f"{transition.guard}: ОТКАЗ ({missing}); вход: "
                f"{_diagnostic_context(merged_context)}"
            )
        log.debug(
            f"Entity {entity_id}: Guard '{transition.guard}' failed for transition "
            f"'{current_state.current_state}' -> '{transition.to_state}' ({missing})"
        )
        return missing

    async def _commit_transition(
        self,
        *,
        entity_id: str,
        definition: FSMDefinition,
        event: str,
        current_state: State,
        transition: Transition,
        new_context: dict[str, Any],
        now: float,
        trace_id: str,
        log: Any,
    ) -> None:
        """Записать выполненный переход: состояние, сохранение, публикация, таймер.

        Порядок обязателен: сначала снимаются таймеры прежнего состояния (только
        на состоявшемся переходе — см. комментарий в `trigger`), затем пишется
        новое состояние, и только потом публикуется событие — подписчик, читающий
        движок, обязан видеть то состояние, о котором ему сообщают (R-02).

        Args:
            entity_id: Идентификатор автомата.
            definition: Описание автомата.
            event: Событие, вызвавшее переход.
            current_state: Состояние до перехода.
            transition: Сработавший переход.
            new_context: Контекст нового состояния.
            now: Момент перехода на монотонных часах.
            trace_id: Идентификатор трассировки.
            log: Журнал с привязанным trace_id.

        Returns:
            Ничего.
        """
        # Таймер прежнего состояния снимается здесь — то есть на
        # выполненном переходе, а не на каждом событии. Отмена означает
        # «ожидание прежнего состояния больше не действует», и только
        # сменившееся состояние делает его недействующим.
        await self._cancel_timers(entity_id, log)

        # Create new state
        new_state = State(current_state=transition.to_state, entered_at=now, context=new_context)

        # Update state
        self._states[entity_id] = new_state
        self._last_transition_time[entity_id] = now
        self.note_transition(entity_id)

        await self._persist_transition(entity_id, transition.to_state, new_context)

        log.info(
            f"Entity {entity_id}: Transition '{current_state.current_state}' -> '{transition.to_state}' "
            f"triggered by '{event}'"
            + (f" (guard: {transition.guard})" if transition.guard else "")
            + (f" (action: {transition.action})" if transition.action else "")
        )

        self._record_transition_decision(entity_id, event, transition.action)

        # Publish after the new state is written, so a subscriber reading the
        # engine always observes the state the event announces (R-02).
        self._publish_transition(
            entity_id, event, current_state.current_state, transition.to_state, trace_id
        )

        self._schedule_transition_timeout(
            entity_id, definition, transition, new_context, trace_id, log
        )

    async def _persist_transition(
        self, entity_id: str, to_state: str, new_context: dict[str, Any]
    ) -> None:
        """Сохранить состояние, если сохранение включено.

        Асинхронный путь обязателен: save_state делает fsync, и вызов прямо из
        корутины перехода останавливал event loop на время записи — при
        нескольких автоматах это складывалось в задержки на WebSocket и
        срабатывания сторожа.

        `entered_at` передаётся настенным временем: по нему после перезапуска
        восстанавливается остаток отложенного перехода. Без него состояние
        восстанавливалось, а таймер нет (Known Issue #78).

        Args:
            entity_id: Идентификатор автомата.
            to_state: Новое состояние.
            new_context: Контекст нового состояния.

        Returns:
            Ничего.
        """
        if self._persistence is None:
            return
        wall_entered_at = time.time()
        saver = getattr(self._persistence, "save_state_async", None)
        if saver is not None:
            await saver(entity_id, to_state, new_context, wall_entered_at)
        else:
            self._persistence.save_state(entity_id, to_state, new_context, wall_entered_at)

    @staticmethod
    def _no_transition_reason(guard_denials: dict[str, str], not_applicable: int) -> str:
        """Назвать причину, по которой ни один переход не подошёл.

        Причина выбирается по тому, чего не хватило: отсутствие данных и
        неподходящее значение — разные ситуации, и оператор должен видеть какую
        именно. Если отказов не было (все переходы прошли), причина прежняя.
        Отсутствие данных важнее прочих (это поломка данных, а не штатная
        работа), дальше — названная причина вроде ночного окна, и только потом
        общее «условие не прошло».

        Args:
            guard_denials: Названные причины отказов по условиям.
            not_applicable: Сколько переходов оказалось неприменимо к прибору.

        Returns:
            Имя причины отказа.
        """
        if not guard_denials and not_applicable:
            # Все подходящие переходы оказались неприменимы к прибору: честное
            # имя — «нет подходящего перехода», а не отказ условия (B66).
            return REASON_NO_TRANSITION
        if REASON_GUARD_DATA_MISSING in guard_denials:
            return REASON_GUARD_DATA_MISSING
        named = next((name for name in guard_denials if name in GUARD_DENIAL_REASONS), None)
        return named or REASON_GUARD_FAILED

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
