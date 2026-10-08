"""Вентиляция по влажности должна реагировать на событие, которое платформа
производит (#67, шаг 4 приёмки спеки 010).

Приёмка вскрыла это в доме 2026-10-08: датчик влажности отчитался, оба
автомата вентиляции получили `humidity_changed` и отказали с `no_transition`.
Шаблон слушает `humidity_high`/`humidity_normal`, а производит событие
`EventRouter` — то есть переход не наступает никогда. Контракт шаблонов
(`src/features/CONTRACT.yaml`) это уже фиксировал как «НЕТ ПРОИСХОДИТЕЛЯ», но
до приёмки оставалось документацией.

Проверка собирает настоящие детали — фабрику, движок и роутер — и отправляет им
событие датчика ровно так, как оно приходит из Home Assistant. Подмена роутера
или шаблона снова сделала бы проверку вакуумной: дефект живёт ровно на стыке
«что платформа публикует» и «что слушает шаблон».

Порог поведения проверяется отдельно: зашитое в имя guard'а `60` не должно
перебивать `humidity_threshold` из манифеста (тот же пункт контракта).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.action_handlers import register_all_actions
from core.control_tracker import ControlTracker
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import register_all_guards
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


#: Датчик влажности так, как его описывает манифест приёмки.
SENSOR = "sensor.spalnya_humidity"

#: Рекуператор приёмки.
FAN = "fan.rekuperator"

#: Идентификатор автомата: устройство + шаблон + приоритет, как в бою.
FSM = f"{FAN}_humidity_ventilation_5"

#: Пауза длиннее `debounce_sec` шаблона (0.5 с) для двух событий подряд.
DEBOUNCE_PLUS = 0.6


class _RecordingDispatcher:
    """Диспетчер, который помнит команды вместо отправки их в HA.

    Обычная заглушка со счётчиком: `MagicMock` проглотил бы проверку
    устройства и сервиса, а дефект находится именно в том, какая команда
    собрана.
    """

    def __init__(self) -> None:
        """Создать пустой список команд.

        Returns:
            Ничего.
        """
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить интент и сказать, что он принят.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            Всегда True — команда считается отправленной.
        """
        self.intents.append(intent)
        return True


def _manifest(threshold: float) -> Manifest:
    """Манифест с одной комнатой: датчик влажности и вентилятор.

    Args:
        threshold: Порог поведения `humidity_threshold`.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe-house",
            name="Probe House",
            owner="probe-owner",
            created_at="2026-01-01T00:00:00Z",
        ),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={"humidity": SENSOR},
                devices=[
                    DeviceConfig(
                        id=FAN,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="humidity_ventilation",
                                priority=5,
                                params={"humidity_threshold": threshold},
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build(threshold: float) -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер: фабрика создаёт автомат, роутер кормит его.

    Args:
        threshold: Порог поведения `humidity_threshold`.

    Returns:
        Движок, роутер и диспетчер, помнящий команды.
    """
    registry = Registry()
    register_all_actions(registry)
    register_all_guards(registry, ControlTracker())
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    manifest = _manifest(threshold)
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


def _state_of(engine: FSMEngine) -> str | None:
    """Текущее состояние автомата вентиляции.

    Args:
        engine: Движок с зарегистрированным автоматом.

    Returns:
        Имя состояния либо None, если состояния нет.
    """
    state = engine.get_state(FSM)
    return state.current_state if state is not None else None


class TestHumidityReachesTheCondition:
    """Событие датчика доходит до условия перехода."""

    @pytest.mark.asyncio
    async def test_humidity_above_threshold_starts_ventilation(self) -> None:
        """Влажность выше порога включает вентиляцию и командует вентилятором."""
        engine, router, dispatcher = _build(threshold=60.0)

        await router.route_state_change(SENSOR, "75", "74")

        assert _state_of(engine) == "ventilating", (
            "датчик сообщил влажность выше порога, а вентиляция не началась: "
            "событие датчика не доходит до условия перехода"
        )
        assert [
            (intent.device_id, intent.domain, intent.service) for intent in dispatcher.intents
        ], "переход состоялся, но команда вентилятору не создана"
        fan_intent = dispatcher.intents[0]
        assert (fan_intent.device_id, fan_intent.domain, fan_intent.service) == (
            FAN,
            "fan",
            "turn_on",
        ), f"команда вентилятору собрана неверно: {fan_intent}"

    @pytest.mark.asyncio
    async def test_humidity_below_threshold_keeps_idle_and_names_the_reason(self) -> None:
        """Влажность ниже порога — штатный отказ, а не дефект данных."""
        engine, router, _ = _build(threshold=60.0)

        await router.route_state_change(SENSOR, "55", "56")

        assert _state_of(engine) == "idle", "при влажности ниже порога вентиляция не идёт"
        assert "guard_failed" in engine.rejection_counts(), (
            "отказ должен называть причину «условие не прошло», иначе владелец "
            f"не отличит его от «данных не было»: {engine.rejection_counts()}"
        )

    @pytest.mark.asyncio
    async def test_unreadable_humidity_is_reported_as_missing_data(self) -> None:
        """Нечитаемое значение — проблема данных, и она называется своей причиной."""
        engine, router, _ = _build(threshold=60.0)

        await router.route_state_change(SENSOR, "unavailable", "55")

        assert _state_of(engine) == "idle", "при нечитаемой влажности вентиляция не идёт"
        assert "guard_data_missing" in engine.rejection_counts(), (
            "нечитаемое значение должно давать причину «данных не было», а не "
            f"«условие не прошло»: {engine.rejection_counts()}"
        )

    @pytest.mark.asyncio
    async def test_ventilation_stops_when_humidity_drops(self) -> None:
        """Опускание влажности возвращает автомат в исходное состояние."""
        engine, router, dispatcher = _build(threshold=60.0)

        await router.route_state_change(SENSOR, "75", "74")
        # Пауза длиннее `debounce_sec` шаблона: события подряд дебаунс
        # отбрасывает, и проверка измеряла бы дебаунс вместо возврата
        # вентиляции. Настоящий датчик так не шлёт — его отчёты разнесены по
        # времени.
        await asyncio.sleep(DEBOUNCE_PLUS)
        await router.route_state_change(SENSOR, "50", "75")

        assert _state_of(engine) == "idle", (
            "влажность упала ниже порога, а вентиляция не остановилась"
        )
        services = [intent.service for intent in dispatcher.intents]
        assert services == ["turn_on", "turn_off"], (
            f"ожидались команда включения и команда выключения, получили {services}"
        )

    @pytest.mark.asyncio
    async def test_threshold_from_manifest_wins_over_guard_name(self) -> None:
        """`humidity_threshold` из манифеста сильнее зашитой в имя guard'а 60."""
        engine, router, _ = _build(threshold=35.0)

        await router.route_state_change(SENSOR, "45", "44")

        assert _state_of(engine) == "ventilating", (
            "порог 35% из манифеста не применён: при 45% вентиляция не идёт, "
            "значит условие читает зашитое в имя guard'а 60 — параметр манифеста "
            "не имеет силы"
        )
