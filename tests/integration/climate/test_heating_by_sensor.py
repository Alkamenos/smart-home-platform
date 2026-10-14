"""Сквозная проверка обогрева: от показания датчика до команды в дом.

Проверяется путь целиком на настоящих объектах движка — не подменой шаблона и
не моком роутера:

`EventRouter` получает показание датчика как **число** в контексте (как это
делает Home Assistant) → решает, что комната холоднее цели → автомат переходит
`IDLE → HEATING` → действие создаёт намерение таймера обогревателя → диспетчер
получает команду.

Отдельно проверяется обратный путь: истечение таймера возвращает автомат в
решение, а не «залипает» в нагреве.

Причина проверки именно на живых объектах: предыдущие находки этого класса были
не в логике, а в соединениях между модулями (событие не порождалось, значение
не доезжало в контекст, условие не было в реестре). Мок на стыке способен
скрыть ровно то, что искали.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


TEMPLATE = Path("src/features/climate_control.yaml")
SETPOINT = 22.0
HYSTERESIS = 0.5
HEATER = "switch.obogrevatel_spalnia"
HEATER_TIMER = "number.obogrevatel_spalnia_countdown"
SENSOR = "sensor.datchik_temperatury_spalnia_temperature"
ROOM = "spalnia"


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в HA."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True

    def services(self) -> list[str]:
        """Сервисы всех команд, что дошли до диспетчера.

        Returns:
            Список имён сервисов.
        """
        return [intent.service for intent in self.intents]


def _manifest(*, managed_by_hardware: bool = False) -> Manifest:
    """Манифест из одной комнаты: датчик температуры и обогреватель.

    Args:
        managed_by_hardware: Пометить комнату как управляемую штатным термостатом.

    Returns:
        Модель манифеста.
    """
    params: dict[str, Any] = {
        "hysteresis": HYSTERESIS,
        "run_minutes": 15,
        "heater_timer": HEATER_TIMER,
    }
    if managed_by_hardware:
        params["managed_by_hardware"] = True
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=ROOM,
                name="Спальня",
                sensors={"temperature": SENSOR},
                devices=[
                    DeviceConfig(
                        id=HEATER,
                        type="climate",
                        behaviors=[
                            BehaviorConfig(template="climate_control", priority=10, params=params)
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build(manifest: Manifest | None = None) -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер климата.

    Args:
        manifest: Манифест; по умолчанию — однокомнатный спальневский.

    Returns:
        Движок, роутер и помнящий команды диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.guards.builtin import register_all_guards

    manifest = manifest or _manifest()
    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


def _context(temperature: Any, **params: Any) -> dict[str, Any]:
    """Контекст события датчика температуры.

    Args:
        temperature: Показание датчика — как его прислал Home Assistant.
        params: Прочие ключи: уставка, гистерезис, комната.

    Returns:
        Словарь контекста.
    """
    return {
        "climate_setpoint": SETPOINT,
        "hysteresis": HYSTERESIS,
        "room": ROOM,
        **params,
    }


class TestHeatingPathEndToEnd:
    """Путь от показания датчика до команды обогревателю."""

    @pytest.mark.asyncio
    async def test_cold_room_sends_timer_command(self) -> None:
        """Комната холоднее цели → обогреватель получает команду на 15 минут.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.5",
            old_state="21.0",
            context=_context("20.5"),
        )

        assert dispatcher.intents, (
            "показание датчика 20.5 при цели 22 не породило ни одной команды: "
            "климат не дошёл до дома"
        )
        timers = [
            i for i in dispatcher.intents if i.domain == "number" and i.service == "set_value"
        ]
        assert timers, (
            f"обогреватель тронут не через свой таймер: "
            f"{[(i.domain, i.service) for i in dispatcher.intents]}"
        )
        assert timers[0].data["value"] == 15, (
            f"в таймер ушло {timers[0].data.get('value')!r} вместо 15 минут"
        )
        assert timers[0].device_id == HEATER_TIMER, (
            f"команда `number.set_value` адресована {timers[0].device_id!r}: Home "
            "Assistant ищет сущность в домене `number`, а переключатель там не "
            "значится — команда отвергается молча (боевой дефект 2026-10-11)"
        )

    @pytest.mark.asyncio
    async def test_warm_room_sends_nothing(self) -> None:
        """Комната в мёртвой зоне — обогреватель не трогаем.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="21.8",
            old_state="20.5",
            context=_context("21.8"),
        )

        assert "set_value" not in dispatcher.services(), (
            f"обогреватель включён в мёртвой зоне: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_unavailable_sensor_sends_nothing(self) -> None:
        """Датчик не отвечает — обогреватель не включаем.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="unavailable",
            old_state="20.5",
            context=_context("unavailable"),
        )

        assert "set_value" not in dispatcher.services(), (
            f"датчик молчит, а обогреватель включился: {dispatcher.services()} — "
            "это перегрев на пустом месте"
        )

    @pytest.mark.asyncio
    async def test_missing_setpoint_sends_nothing(self) -> None:
        """Цели нет — сравнивать не о чем.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="20.0",
            old_state="21.0",
            context={"hysteresis": HYSTERESIS, "room": ROOM},
        )

        assert "set_value" not in dispatcher.services(), (
            "без цели платформа включила обогреватель: включать «на всякий случай» "
            "значит перегревать"
        )

    @pytest.mark.asyncio
    async def test_thermostat_room_is_left_alone(self) -> None:
        """Комната со штатным термостатом платформой не управляется.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build(_manifest(managed_by_hardware=True))

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="18.0",
            old_state="20.5",
            context=_context("18.0", managed_by_hardware=True),
        )

        assert "set_value" not in dispatcher.services(), (
            f"в комнате с термостатом платформа всё равно включила обогреватель: "
            f"{dispatcher.services()} — два регулятора в одной комнате будут драться"
        )

    @pytest.mark.asyncio
    async def test_switched_off_by_owner_stops_commands(self) -> None:
        """`feature_climate` = off — команд нет (право владельца, FR-013).

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="18.0",
            old_state="20.5",
            context=_context("18.0", climate_enabled=False),
        )

        assert "set_value" not in dispatcher.services(), (
            f"климат выключен владельцем, а обогреватель включён: {dispatcher.services()}"
        )


#: События, которые порождает не роутер, а сама платформа. Роутер знает про
#: датчики; эти два знает движок и адаптер.
ENGINE_EVENTS: set[str] = {"timeout"} | {
    f"manual_{action}" for action in ("switch_on", "switch_off", "turn_on", "turn_off")
}


class TestCoolingBranchDoesNotApplyToHeater:
    """Ветка охлаждения к обогревателю не относится (B66)."""

    @pytest.mark.asyncio
    async def test_real_blocker_is_still_named(self) -> None:
        """Настоящая помеха обогреву остаётся названной, а не спрятанной.

        Покой обогревателя теперь оправдан «незачем греть по температуре», но
        выключенный владельцем климат обязан остаться отказом с причиной —
        иначе утренний разбор не увидит, что мешало.

        Returns:
            Ничего.
        """
        engine, router, _dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="18.0",
            old_state="20.5",
            context=_context("18.0", climate_enabled=False),
        )

        counts = engine.rejection_counts()
        assert counts.get("climate_disabled") == 1, f"помеха не названа: {counts}"
        assert "ac_not_allowed" not in counts, f"обогреватель отбивает охлаждение: {counts}"

    @pytest.mark.asyncio
    async def test_heater_never_reports_cooling_denial(self) -> None:
        """Показание температуры по обогревателю не рождает отказ охлаждения.

        Обогреватель не охлаждает, и шаблон климата общий с кондиционером:
        раньше на каждое показание в журнал шло «кондиционер запрещён» — около
        720 записей в сутки. Теперь условие называет переход неприменимым, и
        движок пропускает его молча.

        Returns:
            Ничего.
        """
        engine, router, _dispatcher = _build()

        await router.route_state_change(
            entity_id=SENSOR,
            new_state="24.0",
            old_state="23.9",
            context=_context("24.0"),
        )

        counts = engine.rejection_counts()
        assert "ac_not_allowed" not in counts, f"обогреватель отбивает охлаждение: {counts}"
        assert "ac_forbidden_in_winter" not in counts, f"сезон попал в обогреватель: {counts}"


class TestTemplateListsItsOwnTriggers:
    """Шаблон должен слушать то, что платформа действительно публикует."""

    def test_only_produced_events_are_listened_to(self) -> None:
        """Каждое событие шаблона порождается платформой — роутером или движком.

        Returns:
            Ничего.
        """
        produced: set[str] = set(ENGINE_EVENTS)
        for events in EventRouter.SENSOR_EVENT_MAP.values():
            produced.update(events)

        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        listened = {t["trigger"] for t in template["transitions"] if t.get("trigger")}

        missing = listened - produced
        assert not missing, (
            f"шаблон слушает события, которых никто не публикует: {sorted(missing)}. "
            "Раньше здесь были temperature_low/temperature_high/temperature_reached "
            "— климат не сработал бы никогда"
        )

    def test_every_client_guard_is_registered(self) -> None:
        """Условия шаблона есть в реестре — иначе переход отклонится с ошибкой.

        Returns:
            Ничего.
        """
        from core.guards.builtin import build_guards

        registered = set(build_guards(control_tracker=None))
        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        used = {t["guard"] for t in template["transitions"] if t.get("guard")}

        missing = used - registered
        assert not missing, (
            f"условия шаблона не зарегистрированы: {sorted(missing)}. "
            "Движок отклонит переход, и климат будет выглядеть исправным, "
            "но не сработает"
        )

    def test_every_client_action_is_registered(self) -> None:
        """Действия шаблона есть в реестре обработчиков.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        used = {t["action"] for t in template["transitions"] if t.get("action")}

        missing = used - set(ACTION_HANDLERS)
        assert not missing, f"действия шаблона не зарегистрированы: {sorted(missing)}"


class TestTimerIsArmed:
    """Таймер автомата должен взводиться, иначе переход по нему не сработает.

    Разрыв 2026-10-10 (`research.md` D4): комментарий в шаблоне утверждает, что
    «`timeout_sec` подставляет фабрика из `run_minutes`». Проверено:
    `_timeout_from_params` (`factory.py:30-56`) читает **только**
    `motion_timeout_sec` и **только** для триггера `timeout` — имя `run_minutes`
    не знает. А сам переход `HEATING → IDLE` по `timeout` поля `timeout_sec` не
    содержит, поэтому таймер не взводится и переход не срабатывает никогда.

    Защита «датчик молчит — обогреватель доработает по своему таймеру и
    выключится» (FR-043) на уровне автомата не работает: сам таймер
    обогревателя в Home Assistant сработает, но решение автомата не придёт.
    """

    def test_heating_template_declares_timeout(self) -> None:
        """Переход по таймеру объявляет `timeout_sec`.

        Returns:
            Ничего.
        """
        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

        timeouts = [t for t in template["transitions"] if t.get("trigger") == "timeout"]

        assert timeouts, "в шаблоне должен быть переход по таймеру: без него ожидание не на что"
        for transition in timeouts:
            assert transition.get("timeout_sec"), (
                f"переход {transition['from_state']} -> {transition['to_state']} "
                "по таймеру не задаёт timeout_sec: таймер не взведётся, и "
                "переход никогда не сработает"
            )

    def test_timeout_matches_expected_run_time(self) -> None:
        """Таймер автомата совпадает со временем работы по умолчанию.

        Returns:
            Ничего.
        """
        from core.action_handlers import DEFAULT_HEATER_RUN_MINUTES

        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        timeouts = [t for t in template["transitions"] if t.get("trigger") == "timeout"]

        assert timeouts[0]["timeout_sec"] == DEFAULT_HEATER_RUN_MINUTES * 60, (
            f"таймер автомата ({timeouts[0]['timeout_sec']} с) должен совпадать "
            f"со временем работы обогревателя ({DEFAULT_HEATER_RUN_MINUTES * 60} с): "
            "истекло устройство — истекло и ожидание автомата, иначе решение "
            "приходит позже, чем свет уже погас"
        )
