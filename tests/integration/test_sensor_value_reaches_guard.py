"""Измеримое значение датчика должно доходить до условия перехода.

Сквозной путь: событие Home Assistant → маршрутизатор → контекст перехода →
условие. Проверяется целиком, потому что каждый кусок по отдельности выглядит
рабочим: маршрутизатор доставляет событие, условие читает значение, а между ними
нет ни одного места, где значение кладётся в контекст.

Что проверяется
---------------

1. Влажность доходит до условия и переход разрешён при значении выше порога.
2. Ниже порога — отказ, и это штатная работа, а не поломка.
3. Нечитаемое значение доходит как есть и не превращается в ноль.
4. Значение чужой сущности в решение не попадает: под ролью лежит значение того
   датчика, которому роль принадлежит.
5. Датчик без роли (например, датчик температуры, у которого нет условия) не
   добавляет ничего лишнего и ничего не ломает.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.events.event_router import EventRouter


#: Сущности, как они названы в манифесте.
HUMIDITY = "sensor.bathroom_humidity"
MOTION = "binary_sensor.bathroom_motion"
FAN = "fan.bathroom"

#: Порог из манифеста.
THRESHOLD = 65.0

#: Автомат вентиляции, как его называет фабрика.
FSM_ID = f"{FAN}_humidity_ventilation_5"


def _manifest() -> Any:
    """Манифест с одной комнатой: вентилятор, датчики влажности и движения.

    Returns:
        Объект, которого ждёт маршрутизатор.
    """
    room = SimpleNamespace(
        id="bathroom",
        devices=[SimpleNamespace(id=FAN)],
        sensors={"humidity": HUMIDITY, "motion": MOTION},
    )
    return SimpleNamespace(rooms=[room])


def _engine() -> Any:
    """Движок, у которого вентилятор уже зарегистрирован.

    Returns:
        Подставной движок со списком автоматов комнаты.
    """
    engine = MagicMock()
    engine.get_entities_by_device.side_effect = lambda device_id: (
        [FSM_ID] if device_id == FAN else []
    )
    return engine


def _router() -> EventRouter:
    """Маршрутизатор для ванной.

    Returns:
        Готовый маршрутизатор.
    """
    return EventRouter(_manifest(), _engine())


def _captured_trigger(router: EventRouter) -> MagicMock:
    """Подменить вызов перехода у движка и вернуть заглушку вызова.

    Args:
        router: Маршрутизатор с подменённым движком.

    Returns:
        Заглушка, на которой видно контекст перехода.
    """
    trigger = MagicMock(side_effect=_false_transition)
    router._engine.trigger = trigger
    return trigger


async def _false_transition(*_args: Any, **_kwargs: Any) -> bool:
    """Заглушка перехода: переход не состоялся, как при отказе условия.

    Returns:
        False — переход не выполнен.
    """
    return False


def _context_of(trigger: MagicMock) -> dict[str, Any]:
    """Контекст перехода, дошедший до движка.

    Args:
        trigger: Заглушка вызова перехода.

    Returns:
        Контекст, который движок получил.
    """
    assert trigger.call_args is not None, "переход не вызывался вовсе"
    kwargs = trigger.call_args.kwargs
    return dict(kwargs.get("external_ctx") or {})


#: Свет в комнате, где тот же датчик объявлен датчиком движения.
LIGHT = "light.probe"
LIGHT_FSM = f"{LIGHT}_lighting_10"


class TestOneSensorTwoRoles:
    """Один и тот же датчик в двух ролях: значение нужно обоим автоматам.

    Датчик движения гостиной одновременно может быть источником влажности для
    вентилятора в другой комнате. Раньше роль запоминалась один раз на сущность
    (`setdefault`), и вторая комната получала маршрут, но не значение: условие
    читало ключ, которого в контексте не было, и отказ назывался «данных не
    было» — при живом датчике, который только что отчитался.
    """

    def _shared_sensor_router(self) -> EventRouter:
        """Маршрутизатор, где один датчик — и движение, и влажность.

        Returns:
            Готовый маршрутизатор с двумя комнатами.
        """
        rooms = [
            SimpleNamespace(
                id="gostinaia",
                devices=[SimpleNamespace(id=LIGHT)],
                sensors={"motion": MOTION},
            ),
            SimpleNamespace(
                id="kabinet",
                devices=[SimpleNamespace(id=FAN)],
                sensors={"humidity": MOTION},
            ),
        ]
        engine = MagicMock()
        engine.get_entities_by_device.side_effect = lambda device_id: (
            [LIGHT_FSM] if device_id == LIGHT else [FSM_ID] if device_id == FAN else []
        )
        return EventRouter(SimpleNamespace(rooms=rooms), engine)

    @pytest.mark.asyncio
    async def test_value_reaches_the_second_role(self) -> None:
        """Под второй ролью значение тоже должно доехать до условия."""
        router = self._shared_sensor_router()
        trigger = _captured_trigger(router)

        await router.route_state_change(MOTION, new_state="75", old_state="70")

        fan_call = [c for c in trigger.call_args_list if c.kwargs.get("entity_id") == FSM_ID]
        assert fan_call, f"переход вентилятора не вызывался вовсе: {trigger.call_args_list}"
        context = dict(fan_call[0].kwargs.get("external_ctx") or {})
        assert context.get("humidity") == pytest.approx(75.0), (
            "датчик объявлен в этой комнате датчиком влажности, а значение лежит "
            f"только под чужой ролью: {context}"
        )

    @pytest.mark.asyncio
    async def test_first_role_keeps_its_own_name(self) -> None:
        """Первая роль не должна потерять значение из-за второй.

        Значение здесь настоящее движение (`on`), а не число: событие движения
        роутер отфильтровывает по состоянию, и выдуманное «75» до света не
        дошло бы вовсе — проверяла бы фильтр, а не роль.
        """
        router = self._shared_sensor_router()
        trigger = _captured_trigger(router)

        await router.route_state_change(MOTION, new_state="on", old_state="off")

        light_call = [c for c in trigger.call_args_list if c.kwargs.get("entity_id") == LIGHT_FSM]
        assert light_call, f"переход света не вызывался: {trigger.call_args_list}"
        context = dict(light_call[0].kwargs.get("external_ctx") or {})
        assert context.get("motion") == "on", (
            f"значение датчика движения не дошло до своего автомата: {context}"
        )


class TestHumidityReachesTransition:
    """Влажность доходит до условия перехода."""

    @pytest.mark.asyncio
    async def test_value_is_in_transition_context(self) -> None:
        """Значение датчика едет в контексте под именем своей роли.

        Ключ совпадает с тем, который читает условие влажности. Раньше контекст
        содержал только имена состояний, и условие читало ключ, которого там
        никогда не было.
        """
        router = _router()
        trigger = _captured_trigger(router)

        await router.route_state_change(HUMIDITY, new_state="70.5", old_state="60")

        assert _context_of(trigger).get("humidity") == pytest.approx(70.5), (
            f"влажность не дошла до контекста перехода: {_context_of(trigger).get('humidity')!r}"
        )

    @pytest.mark.asyncio
    async def test_integer_value_is_converted(self) -> None:
        """Целое значение приходит числом, а не строкой.

        Иначе условие сравнивало бы строку с числом, и сравнение молчало бы не в
        пользу перехода.
        """
        router = _router()
        trigger = _captured_trigger(router)

        await router.route_state_change(HUMIDITY, new_state="70", old_state="60")

        assert isinstance(_context_of(trigger).get("humidity"), float)

    @pytest.mark.asyncio
    async def test_entity_and_states_still_present(self) -> None:
        """Прежние поля контекста не потеряны.

        Доставка состояний и маршрутизация держатся на этих трёх полях; правка
        аддитивна и не должна была их тронуть.
        """
        router = _router()
        trigger = _captured_trigger(router)

        await router.route_state_change(HUMIDITY, new_state="70", old_state="60")
        context = _context_of(trigger)

        assert context["entity_id"] == HUMIDITY
        assert context["new_state"] == "70"
        assert context["old_state"] == "60"


class TestUnreadableValueIsNotZero:
    """Нечитаемое значение не превращается в ной."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["unavailable", "", "нет данных"])
    async def test_value_stays_readable_as_string(self, value: str) -> None:
        """Значение доходит как есть, и условие может отказать по понятной причине."""
        router = _router()
        trigger = _captured_trigger(router)

        await router.route_state_change(HUMIDITY, new_state=value, old_state="60")

        measured = _context_of(trigger).get("humidity")
        assert measured == value, (
            f"нечитаемое значение превратилось в {measured!r}: молчаливый ноль "
            f"выдал бы заведомо ложное «влажность 0» за честное решение"
        )


class TestForeignValueDoesNotLeak:
    """Под ролью лежит значение своего датчика."""

    @pytest.mark.asyncio
    async def test_other_sensor_does_not_fill_role(self) -> None:
        """Событие датчика движения не подставляет «влажность».

        Иначе переход по влажности решался бы по данным чужого датчика: значение
        есть, оно прочитано, а относится к другой физической величине.
        """
        router = _router()
        trigger = _captured_trigger(router)

        await router.route_state_change(MOTION, new_state="on", old_state="off")
        context = _context_of(trigger)

        assert "humidity" not in context, (
            f"значение датчика движения попало в контекст как влажность: {context}"
        )

    @pytest.mark.asyncio
    async def test_motion_event_still_delivers_its_own_context(self) -> None:
        """Событие движения доставляется как и раньше."""
        router = _router()
        trigger = _captured_trigger(router)

        await router.route_state_change(MOTION, new_state="on", old_state="off")
        context = _context_of(trigger)

        assert context["entity_id"] == MOTION
        assert context["new_state"] == "on"


class TestGuardDecidesOnRealValue:
    """Условие принимает решение по фактическому значению."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("value", "allowed"),
        [(70.0, True), (65.1, True), (64.9, False), (50.0, False)],
    )
    async def test_transition_follows_threshold(self, value: float, allowed: bool) -> None:
        """Порог из манифеста решает судьбу перехода.

        Порог передаётся в контекст параметром поведения, как его кладёт движок;
        здесь он подставляется напрямую, потому что проверяется решение условия,
        а не путь параметра.
        """
        from core.guards.builtin import build_guards

        router = _router()
        trigger = _captured_trigger(router)
        tracker = MagicMock()
        tracker.was_manual_within.return_value = False
        guard = build_guards(tracker)["humidity_above_60"]

        await router.route_state_change(HUMIDITY, new_state=str(value), old_state="60")
        context = {**_context_of(trigger), "humidity_threshold": THRESHOLD}

        assert guard(None, context) is allowed, (
            f"влажность {value} при пороге {THRESHOLD}: решение неверно"
        )
