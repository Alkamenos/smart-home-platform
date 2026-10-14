"""Вечерний (декоративный) свет: закат включает, а выключает — по своему часу.

Требования владельца (2026-10-09, боевой дефект того же вечера):

- **Гирлянда на террасе** была описана обычным освещением (`lighting`) и вела
  себя как свет от движения: включалась при проходе и **гасла через 10 минут**
  (`motion_timeout_sec`). Декоративный свет так себя не ведёт.
- Должна: включаться **по закату** (датчик освещённости сломан и ждёт замены) и
  гаснуть, когда владелец включил «мы спим».
- **Ночное освещение**: включаться по закату и гореть **до рассвета**.

Проверки идут по настоящим объектам движка: события порождает адаптер,
доставляет контейнер, а решение принимает шаблон. Мок на стыке скрыл бы ровно
то, что искалось — как уже случилось с формой события солнца.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.fsm.engine import SAFETY_EVENTS, FSMEngine
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


TEMPLATE = Path("src/features/deco_light.yaml")
GARLAND = "light.girlianda_terassa"
NIGHT_LIGHT = "light.group_nochnoe_osveshcheni"


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


def _manifest(device_id: str, off_by: str) -> Manifest:
    """Манифест с одним декоративным светильником.

    Args:
        device_id: Светильник под проверкой.
        off_by: Правило выключения: `sleep` или `sunrise`.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="terassa",
                name="Терраса",
                sensors={},
                devices=[
                    DeviceConfig(
                        id=device_id,
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="deco_light",
                                priority=10,
                                params={"off_by": off_by},
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _engine(device_id: str, off_by: str) -> tuple[FSMEngine, _RecordingDispatcher]:
    """Собрать движок с декоративным светом.

    Args:
        device_id: Светильник под проверкой.
        off_by: Правило выключения.

    Returns:
        Движок и помнящий команды диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.control_tracker import ControlTracker
    from core.guards.builtin import register_all_guards

    registry = Registry()
    register_all_guards(registry, ControlTracker())
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    manifest = _manifest(device_id, off_by)
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, dispatcher


async def _fire(engine: FSMEngine, dispatcher: _RecordingDispatcher, event: str) -> None:
    """Отправить событие всем автоматам, у которых есть переход.

    Args:
        engine: Движок автоматов.
        dispatcher: Помнящий команды диспетчер (для сброса между шагами).
        event: Имя события.
    """
    from core.services.day_cycle import deliver_to_automata

    dispatcher.intents.clear()
    await deliver_to_automata(engine, event)


class TestGarlandFollowsSunsetAndSleep:
    """Гирлянда: закат включает, «мы спим» выключает."""

    @pytest.mark.asyncio
    async def test_sunset_turns_garland_on(self) -> None:
        """Закат — гирлянда загорается сама.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(GARLAND, "sleep")

        await _fire(engine, dispatcher, "sunset_started")

        assert "turn_on" in dispatcher.services(), (
            f"гирлянда не загорелась по закату: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_sleep_turns_garland_off(self) -> None:
        """«Мы спим» — гирлянда гаснет.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(GARLAND, "sleep")
        await _fire(engine, dispatcher, "sunset_started")

        await _fire(engine, dispatcher, "sleep_started")

        assert "turn_off" in dispatcher.services(), (
            f"гирлянда не погасла по модификатору «мы спим»: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_morning_turns_garland_off(self) -> None:
        """Утреннее событие платформы тоже гасит гирлянду.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(GARLAND, "sleep")
        await _fire(engine, dispatcher, "sunset_started")

        await _fire(engine, dispatcher, "day_started")

        assert "turn_off" in dispatcher.services(), (
            f"гирлянда горела после утреннего события: {dispatcher.services()}"
        )


class TestNightLightBurnsUntilSunrise:
    """Ночное освещение: закат включает, рассвет выключает."""

    @pytest.mark.asyncio
    async def test_sunset_turns_night_light_on(self) -> None:
        """Закат — ночное освещение загорается.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(NIGHT_LIGHT, "sunrise")

        await _fire(engine, dispatcher, "sunset_started")

        assert "turn_on" in dispatcher.services()

    @pytest.mark.asyncio
    async def test_sunrise_turns_night_light_off(self) -> None:
        """Рассвет — ночное освещение гаснет.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(NIGHT_LIGHT, "sunrise")
        await _fire(engine, dispatcher, "sunset_started")

        await _fire(engine, dispatcher, "sunrise_started")

        assert "turn_off" in dispatcher.services(), (
            f"ночное освещение не погасло по рассвету: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_sleep_alone_does_not_extinguish_night_light(self) -> None:
        """Модификатор «мы спим» ночное освещение не гасит — оно живёт до рассвета.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(NIGHT_LIGHT, "sunrise")
        await _fire(engine, dispatcher, "sunset_started")

        await _fire(engine, dispatcher, "sleep_started")

        assert "turn_off" not in dispatcher.services(), (
            "ночное освещение погасло по «мы спим», хотя живёт до рассвета: "
            "в предрассветные часы участок остался бы тёмным"
        )


class TestDecoLightDoesNotFollowMotion:
    """Боевой дефект: гирлянда гасла через 10 минут после прохода."""

    @pytest.mark.asyncio
    async def test_no_motion_transitions_at_all(self) -> None:
        """В шаблоне нет ни одного перехода по движению.

        Returns:
            Ничего.
        """
        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        triggers = {t["trigger"] for t in template["transitions"]}

        assert "motion_detected" not in triggers, (
            "декоративный свет не должен реагировать на движение: гирлянда "
            "включалась по проходу и гасла через motion_timeout_sec"
        )
        assert "motion_cleared" not in triggers
        # Таймер у вечернего света есть, но **не** удержание по движению: это срок
        # ручного оверрайда (60 минут, BACKLOG B57) — после ручного включения свет
        # возвращается к автоматике. Удержания «десять минут после прохода» нет.
        overrides = [t for t in template["transitions"] if t["trigger"] == "timeout"]
        assert overrides, "нет возврата к автоматике по сроку оверрайда"
        assert all(
            t["from_state"] == "ON_MANUAL" and t["timeout_sec"] == 3600.0 for t in overrides
        ), f"таймер вечернего света не про оверрайд: {overrides}"

    @pytest.mark.asyncio
    async def test_motion_event_leaves_decor_light_alone(self) -> None:
        """Событие движения не трогает декоративный свет.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(GARLAND, "sleep")

        await _fire(engine, dispatcher, "motion_detected")

        assert dispatcher.services() == [], (
            f"движение подействовало на декоративный свет: {dispatcher.services()}"
        )


class TestDecoLightBypassesManualLockout:
    """Закат, рассвет и отбой важнее ручной блокировки."""

    def test_day_change_events_are_safety_events(self) -> None:
        """События смены суток обходят локаут.

        Returns:
            Ничего.
        """
        for event in ("sunset_started", "sunrise_started", "day_started", "sleep_started"):
            assert event in SAFETY_EVENTS, (
                f"событие `{event}` не в SAFETY_EVENTS: человек включил гирлянду "
                "из приложения, и без обхода локаута она горела бы до утра"
            )


class TestDecoLightIsExtinguishedEvenWhenAutomatonIsOff:
    """Гирлянда, включённая руками, должна погаснуть по отбою.

    Автомат о такой гирлянде не знает: решение пришло не от него, состояние
    у него OFF. Переход «OFF → OFF без действия» оставил бы её гореть до утра —
    ровно тот дефект, из-за которого шаблон и писался.
    """

    @pytest.mark.asyncio
    async def test_sleep_extinguishes_manually_switched_on_garland(self) -> None:
        """Автомат выключен, свет горит — «мы спим» всё равно гасит.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(GARLAND, "sleep")

        await _fire(engine, dispatcher, "sleep_started")

        assert "turn_off" in dispatcher.services(), (
            f"гирлянда, включённая руками, не погасла по отбою: {dispatcher.services()}"
        )

    @pytest.mark.asyncio
    async def test_sunrise_extinguishes_night_light_known_to_be_off(self) -> None:
        """Рассвет гасит ночное освещение, даже если автомат считает его выключенным.

        Returns:
            Ничего.
        """
        engine, dispatcher = _engine(NIGHT_LIGHT, "sunrise")

        await _fire(engine, dispatcher, "sunrise_started")

        assert "turn_off" in dispatcher.services()


class TestDecoTemplateIsComplete:
    """Шаблон должен ссылаться только на порождаемые события и условия."""

    def test_events_are_produced_by_platform(self) -> None:
        """Каждое событие шаблона порождается платформой.

        Returns:
            Ничего.
        """
        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        listened = {t["trigger"] for t in template["transitions"] if t.get("trigger")}

        produced = {
            "sunset_started",
            "sunrise_started",
            "sleep_started",
            "day_started",
            # Ручное действие человека и срок оверрайда: событие доставляет
            # адаптер (изменение состояния сделал пользователь), а таймер —
            # движок (BACKLOG B57).
            "manual_switch_on",
            "manual_switch_off",
            "timeout",
            # Прибор разошёлся с решением — сторож просит автомат повторить
            # решение (BACKLOG B64).
            "device_state_diverged",
        }
        assert not (listened - produced), (
            f"шаблон слушает события, которых никто не порождает: {sorted(listened - produced)}"
        )

    def test_guards_are_registered(self) -> None:
        """Условия шаблона зарегистрированы в реестре движка.

        Returns:
            Ничего.
        """
        from core.guards.builtin import build_guards

        registered = set(build_guards(control_tracker=None))
        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        used = {t["guard"] for t in template["transitions"] if t.get("guard")}

        assert not (used - registered), f"условия не зарегистрированы: {sorted(used - registered)}"

    def test_actions_are_registered(self) -> None:
        """Действия шаблона есть в реестре обработчиков.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        template = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
        used = {t["action"] for t in template["transitions"] if t.get("action")}

        assert not (used - set(ACTION_HANDLERS)), (
            f"действия не зарегистрированы: {sorted(used - set(ACTION_HANDLERS))}"
        )


class TestSunsetEventIsRaisedOnlyOnChange:
    """Закат рождается при смене состояния солнца, а не на каждый отклик."""

    @pytest.mark.asyncio
    async def test_adapter_raises_sunset_once(self) -> None:
        """Смена состояния солнца порождает одно уведомление.

        Returns:
            Ничего.
        """
        from adapters.ha_adapter import SimpleHAWebSocketClient

        client = SimpleHAWebSocketClient(url="ws://localhost:8123", token="t")
        calls: list[str] = []
        client.on_sunset = lambda: asyncio.sleep(0, result=calls.append("sunset"))

        await client._deliver(  # noqa: SLF001
            {
                "entity_id": "sun.sun",
                "new_state": {"entity_id": "sun.sun", "state": "below_horizon"},
                "old_state": {"entity_id": "sun.sun", "state": "above_horizon"},
            }
        )
        first = len(calls)
        await client._deliver(  # noqa: SLF001
            {
                "entity_id": "sun.sun",
                "new_state": {"entity_id": "sun.sun", "state": "below_horizon"},
                "old_state": {"entity_id": "sun.sun", "state": "below_horizon"},
            }
        )

        assert first == 1, (
            f"закат порождён {first} раз: смена состояния должна давать одно "
            "уведомление, иначе вечерний свет включался бы по кругу"
        )
        assert len(calls) == 1, "повторное событие с тем же состоянием закат не порождает"

    @pytest.mark.asyncio
    async def test_first_reading_after_connect_is_not_a_sunset(self) -> None:
        """Первое состояние солнца после подключения закатом не считается.

        Returns:
            Ничего.
        """
        from adapters.ha_adapter import SimpleHAWebSocketClient

        client = SimpleHAWebSocketClient(url="ws://localhost:8123", token="t")
        calls: list[str] = []
        client.on_sunset = lambda: asyncio.sleep(0, result=calls.append("sunset"))

        await client._deliver(  # noqa: SLF001
            {
                "entity_id": "sun.sun",
                "new_state": {"entity_id": "sun.sun", "state": "below_horizon"},
                "old_state": {"entity_id": "sun.sun", "state": "unknown"},
            }
        )

        assert calls == [], (
            "платформа не знает, что было до подключения: выдуманный закат среди "
            "ночи включил бы гирлянду, когда все спят"
        )
