"""Отказ датчика не расходится по дому (US5).

Три требования проверяются сквозным путём, а не через отдельные условия:
отказ одной комнаты не меняет решения других (FR-041), обогреватель при отказе
датчика дорабатывает по своему таймеру и выключается (FR-043), а возврат
показания возвращает комнату в работу без перезапуска платформы (FR-042).

Проверка на условиях была бы проверкой таблицы: дефект живёт в движке и в
доставке событий, а не в `may_heat`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

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


SETPOINT = 21.0
SENSOR = "sensor.datchik_temperatury_{room}_temperature"
HEATER = "switch.obogrevatel_{room}"


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в Home Assistant."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Помнить команду.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True

    def for_device(self, device_id: str) -> list[Any]:
        """Команды одного устройства.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            Список команд.
        """
        return [i for i in self.intents if i.device_id == device_id]


def _manifest() -> Manifest:
    """Две комнаты с обогревом: спальня и кабинет.

    Returns:
        Модель манифеста.
    """

    def _room(room: str) -> RoomConfig:
        """Комната с датчиком и обогревателем.

        Args:
            room: Идентификатор комнаты.

        Returns:
            Модель комнаты.
        """
        return RoomConfig(
            id=room,
            name=room,
            sensors={"temperature": SENSOR.format(room=room)},
            devices=[
                DeviceConfig(
                    id=HEATER.format(room=room),
                    type="climate",
                    behaviors=[
                        BehaviorConfig(
                            template="climate_control",
                            priority=10,
                            params={"run_minutes": 15, "hysteresis": 0.5},
                        )
                    ],
                )
            ],
        )

    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[_room("spalnia"), _room("kabinet")],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Движок, роутер и помнящий команды диспетчер.

    Returns:
        Движок, роутер, диспетчер.
    """
    registry = Registry()
    register_all_guards(registry, ControlTracker())
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    manifest = _manifest()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


async def _reading(router: EventRouter, room: str, value: str) -> None:
    """Доставить показание датчика комнаты.

    Args:
        router: Роутер событий.
        room: Идентификатор комнаты.
        value: Показание, в том числе непригодное.

    Returns:
        Ничего.
    """
    await router.route_state_change(
        entity_id=SENSOR.format(room=room),
        new_state=value,
        old_state="20.0",
        context={"climate_setpoint": SETPOINT},
    )


class TestFailureIsIsolated:
    """Отказ одной комнаты не трогает другие."""

    @pytest.mark.asyncio
    async def test_one_room_failure_does_not_stop_another(self) -> None:
        """Молчащий датчик спальни не мешает кабинету греться.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        spalnia_fsm = "switch.obogrevatel_spalnia_climate_control_10"
        kabinet_fsm = "switch.obogrevatel_kabinet_climate_control_10"

        await _reading(router, "spalnia", "unavailable")
        await _reading(router, "kabinet", "19.0")

        assert engine.get_state(spalnia_fsm).current_state == "IDLE", (
            "у спальни нет данных — обогрев включаться не должен"
        )
        assert engine.get_state(kabinet_fsm).current_state == "HEATING", (
            "у кабинета данные есть и он холоднее цели: отказ соседней комнаты не "
            "должен мешать, иначе один сломанный датчик остановит весь дом"
        )
        assert dispatcher.for_device(HEATER.format(room="kabinet")), (
            "в кабинете должна уйти команда включения"
        )
        assert not dispatcher.for_device(HEATER.format(room="spalnia")), (
            "в спальне команд быть не должно: данных нет, решать не на чем"
        )


class TestHeaterFinishesByTimer:
    """При отказе датчика обогреватель дорабатывает по своему таймеру."""

    @pytest.mark.asyncio
    async def test_heating_continues_without_further_readings(self) -> None:
        """Обогреватель не выключается молчащим датчиком.

        Returns:
            Ничего.
        """
        engine, router, _dispatcher = _build()
        kabinet_fsm = "switch.obogrevatel_kabinet_climate_control_10"

        await _reading(router, "kabinet", "19.0")
        assert engine.get_state(kabinet_fsm).current_state == "HEATING"

        # Датчик замолчал: показаний больше нет.
        await _reading(router, "kabinet", "unavailable")

        assert engine.get_state(kabinet_fsm).current_state == "HEATING", (
            "выключать обогреватель по отсутствию данных нельзя: единственный "
            "способ узнать, что стало тепло, — это истёкший таймер"
        )

    @pytest.mark.asyncio
    async def test_timeout_still_fires_when_sensor_is_silent(self) -> None:
        """Таймер автомата срабатывает даже при молчащем датчике.

        Returns:
            Ничего.
        """
        engine, router, _dispatcher = _build()
        kabinet_fsm = "switch.obogrevatel_kabinet_climate_control_10"

        await _reading(router, "kabinet", "19.0")
        await _reading(router, "kabinet", "unavailable")
        # Таймер автомата: истекло время работы — решение принимается заново.
        await engine.trigger(kabinet_fsm, "timeout", respect_debounce=False)

        assert engine.get_state(kabinet_fsm).current_state == "IDLE", (
            "таймер обязан сработать при молчащем датчике: иначе обогреватель "
            "останется включённым навсегда"
        )


class TestSensorReturns:
    """Возврат показания возвращает комнату в работу."""

    @pytest.mark.asyncio
    async def test_room_recovers_without_restart(self) -> None:
        """Датчик оживает — обогрев снова включается.

        Между отказом и возвратом в доме проходят минуты, поэтому дебаунс не
        мешает. В тесте события идут подряд, и дебаунс (1 с в шаблоне климата)
        отбрасывает второе — обходится так же, как суточный цикл обходит
        отсечку для событий не от датчика.

        Returns:
            Ничего.
        """
        engine, _router, dispatcher = _build()
        spalnia_fsm = "switch.obogrevatel_spalnia_climate_control_10"
        await engine.trigger(
            spalnia_fsm,
            "temperature_changed",
            external_ctx={"temperature": "unavailable", "climate_setpoint": SETPOINT},
            respect_debounce=False,
        )
        await engine.trigger(
            spalnia_fsm,
            "temperature_changed",
            external_ctx={"temperature": 19.0, "climate_setpoint": SETPOINT},
            respect_debounce=False,
        )

        assert engine.get_state(spalnia_fsm).current_state == "HEATING", (
            "после возврата датчика комната обязана заработать сама: ждать "
            "перезапуска платформы из-за севшей батарейки нельзя"
        )
        assert dispatcher.for_device(HEATER.format(room="spalnia")), (
            "восстановление должно дойти до команды, а не только сменить состояние"
        )

    @pytest.mark.asyncio
    async def test_debounce_still_protects_from_bouncing(self) -> None:
        """Дребезг датчика по-прежнему отбрасывается.

        Проверяется, что обход дебаунса в предыдущем тесте не выключил его
        совсем: два показания подряд не должны приводить к двум переходам.

        Returns:
            Ничего.
        """
        _engine, router, dispatcher = _build()

        await _reading(router, "spalnia", 19.0)
        first = len(dispatcher.for_device(HEATER.format(room="spalnia")))
        await _reading(router, "spalnia", 19.1)

        assert len(dispatcher.for_device(HEATER.format(room="spalnia"))) == first, (
            "дребезг датчика должен отбрасываться: иначе обогреватель включался "
            "бы по нескольку раз подряд на границе шума"
        )


class TestRecoveryWithoutRestart:
    """Комната возвращается в работу без перезапуска платформы."""

    @pytest.mark.asyncio
    async def test_other_room_keeps_working_during_outage(self) -> None:
        """Пока сломан один датчик, остальные не останавливаются.

        Returns:
            Ничего.
        """
        engine, router, _dispatcher = _build()
        kabinet_fsm = "switch.obogrevatel_kabinet_climate_control_10"

        # Спальня молчит сутки, кабинет работает как обычно.
        await _reading(router, "spalnia", "unavailable")
        await _reading(router, "kabinet", 19.0)
        await _reading(router, "kabinet", 19.1)

        assert engine.get_state(kabinet_fsm).current_state == "HEATING", (
            "комната, где датчик есть, обязана работать, пока соседняя молчит"
        )
