"""Transition execution for the FSM engine (spec 018, US4).

Extracted from FSMEngine: resolving an event into a transition, collecting the
context, checking the guard, committing the new state and publishing it.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import time
import uuid
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
from core.fsm.models import FSMDefinition, State, Transition
from core.models.manifest import AutomationDomainRules


if TYPE_CHECKING:
    from core.persistence.state_persistence import StatePersistence


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


LIGHT_OFF_ACTIONS: Final[frozenset[str]] = frozenset({"turn_off_light", "turn_off_night_light"})


class TransitionMixin:
    """Run transitions for one automaton."""

    _definitions: dict[str, FSMDefinition]
    _states: dict[str, State]
    _last_transition_time: dict[str, float]
    _persistence: StatePersistence | None

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
        #
        # Исключение — само-переход с ``extends_timeout: false``. Такой переход
        # не меняет состояние и не продлевает срок: таймер страховки должен
        # сработать в момент, отсчитанный от входа в состояние, а не от
        # последнего показания датчика (B12: иначе обогреватель не выключался
        # по своему сроку никогда). Поэтому прежний таймер остаётся взведённым,
        # а время входа и сохранённая метка не сдвигаются.
        keeps_deadline = (
            transition.from_state == transition.to_state and not transition.extends_timeout
        )
        if not keeps_deadline:
            await self._cancel_timers(entity_id, log)

        # Create new state
        entered_at = current_state.entered_at if keeps_deadline else now
        new_state = State(
            current_state=transition.to_state, entered_at=entered_at, context=new_context
        )

        # Update state
        self._states[entity_id] = new_state
        self._last_transition_time[entity_id] = now
        self.note_transition(entity_id)

        # Сохранённая метка входа тоже остаётся исходной: после перезапуска
        # остаток таймера считается от неё, и само-переход не должен дарить
        # состоянию новый срок.
        persisted_at = (
            time.time() - max(0.0, now - current_state.entered_at) if keeps_deadline else None
        )
        await self._persist_transition(entity_id, transition.to_state, new_context, persisted_at)

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

        if not keeps_deadline:
            self._schedule_transition_timeout(
                entity_id, definition, transition, new_context, trace_id, log
            )

    async def _persist_transition(
        self,
        entity_id: str,
        to_state: str,
        new_context: dict[str, Any],
        wall_entered_at: float | None = None,
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
            wall_entered_at: Настенное время входа, если оно не совпадает с
                текущим моментом. Нужно само-переходам, которые не продлевают
                срок состояния: иначе перезапуск подарил бы им новый срок.

        Returns:
            Ничего.
        """
        if self._persistence is None:
            return
        if wall_entered_at is None:
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
