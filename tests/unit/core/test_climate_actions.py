"""Проверки действий климата: какая команда уходит в дом и с чем.

Требование владельца (спека 011, FR-004): обогреватель включается **через свой
собственный таймер** — «на 15 минут», а не «включить и ждать, пока датчик
скажет». Это даёт защиту от перегрева, если датчик отвалится: таймер истечёт
сам.

Действия климата живут рядом с `climate_heat`/`climate_cool`/`climate_off`, но
относятся к другому устройству: обогреватель — это `switch.*` с таймером
`number.*`, а не `climate.*`. Поэтому здесь домены `number` и `switch`.

Покрытие новых действий — 100% (конституция II).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


RUN_MINUTES = 15


def _action(name: str) -> Any:
    """Взять действие по имени из реестра.

    Args:
        name: Имя действия.

    Returns:
        Функция (state, context) -> CommandIntent.

    Raises:
        AssertionError: действия нет в реестре — шаблон его перехода отклонит.
    """
    assert name in ACTION_HANDLERS, (
        f"действие `{name}` не зарегистрировано: в реестре {sorted(ACTION_HANDLERS)}"
    )
    return ACTION_HANDLERS[name]


def _ctx(**params: Any) -> dict[str, Any]:
    """Контекст перехода климата.

    Args:
        params: Ключи контекста.

    Returns:
        Словарь контекста.
    """
    return params


class TestHeaterStartsThroughItsOwnTimer:
    """Основной путь: обогреватель получает команду «работай N минут»."""

    def test_timer_command_is_number_set_value(self) -> None:
        """Намерение уходит в домен `number` со значением в минутах.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        intent = action(
            None,
            _ctx(
                entity_id="switch.obogrevatel_spalnia",
                heater_timer="number.obogrevatel_spalnia_countdown",
                run_minutes=RUN_MINUTES,
            ),
        )

        assert intent is not None, (
            "действие молча не создало команду: платформа решила греть и ничего не сказала"
        )
        assert intent.domain == "number", (
            f"команда ушла в домен {intent.domain!r}: таймер обогревателя — это "
            "`number`, и light/climate вернули бы ошибку Home Assistant"
        )
        assert intent.service == "set_value"
        assert intent.data["value"] == RUN_MINUTES, (
            f"в команду ушло {intent.data.get('value')!r} вместо {RUN_MINUTES}: "
            "таймер должен получить именно длительность работы"
        )
        assert intent.device_id == "switch.obogrevatel_spalnia"

    def test_run_minutes_falls_back_to_default(self) -> None:
        """Без заданной длительности — 15 минут: значение по умолчанию.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        intent = action(
            None,
            _ctx(
                entity_id="switch.obogrevatel_kabinet",
                heater_timer="number.obogrevatel_kabinet_countdown",
            ),
        )

        assert intent is not None
        assert intent.data["value"] == 15, (
            "без run_minutes команда не должна уходить с пустым значением: "
            "таймер обогревателя без времени работы включает греть навсегда"
        )


class TestHeaterFallsBackWhenTimerIsAbsent:
    """Обогреватель без таймера включается по датчику, но платформа говорит об этом."""

    def test_without_timer_entity_switch_turn_on(self) -> None:
        """Таймер не задан — обычное включение `switch`.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        intent = action(
            None,
            _ctx(entity_id="switch.obogrevatel_kabinet", run_minutes=RUN_MINUTES),
        )

        assert intent is not None
        assert intent.domain == "switch", (
            f"без таймера обогреватель включается как switch, а не {intent.domain!r}"
        )
        assert intent.service == "turn_on"

    def test_source_records_that_timer_was_missing(self) -> None:
        """Источник команды различает два пути — по нему видно, какой сработал.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        with_timer = action(
            None,
            _ctx(entity_id="switch.x", heater_timer="number.x_countdown", run_minutes=RUN_MINUTES),
        )
        without_timer = action(None, _ctx(entity_id="switch.x", run_minutes=RUN_MINUTES))

        assert with_timer is not None
        assert without_timer is not None
        assert with_timer.source != without_timer.source, (
            "оба пути помечены одинаково: в журнале нельзя отличить работу через "
            "таймер от работы без него — а это разный уровень защиты от перегрева"
        )


class TestHeaterTurnsOff:
    """Выключение обогревателя."""

    def test_turn_off_is_switch_service(self) -> None:
        """Выключение — это `switch.turn_off` от самого обогревателя.

        Returns:
            Ничего.
        """
        action = _action("heater_off")

        intent = action(None, _ctx(entity_id="switch.obogrevatel_spalnia"))

        assert intent is not None
        assert intent.domain == "switch"
        assert intent.service == "turn_off"
        assert intent.device_id == "switch.obogrevatel_spalnia"

    def test_missing_entity_returns_none_and_warns(self) -> None:
        """Без устройства команда не создаётся — и это видно в журнале.

        Returns:
            Ничего.
        """
        action = _action("heater_off")

        assert action(None, _ctx()) is None, (
            "без entity_id действие обязано вернуть None: молчаливое «решение "
            "выключить» без устройства выглядит как выполненный обогрев"
        )


class TestAirConditionerCommands:
    """Команды кондиционеру — другому устройству и в другом домене."""

    def test_cooling_sets_temperature_to_comfort_max(self) -> None:
        """Охлаждение задаёт потолок комфорта, а не произвольное число.

        Returns:
            Ничего.
        """
        action = _action("ac_cool_on")

        intent = action(
            None,
            _ctx(entity_id="climate.esphome_web_0d22a4_ac_name", comfort_max=25.0),
        )

        assert intent is not None
        assert intent.domain == "climate", f"ожидался домен climate, получено {intent.domain!r}"
        assert intent.service == "set_temperature"
        assert intent.data["temperature"] == 25.0, (
            f"в команду ушло {intent.data.get('temperature')!r} вместо потолка 25.0: "
            "охлаждать надо ровно до той температуры, которую владелец назвал "
            "комфортной"
        )

    def test_winter_protection_turns_ac_off(self) -> None:
        """Защита зимой — выключение кондиционера.

        Returns:
            Ничего.
        """
        action = _action("ac_forced_off")

        intent = action(None, _ctx(entity_id="climate.esphome_web_0d22a4_ac_name"))

        assert intent is not None
        assert intent.domain == "climate"
        assert intent.service == "turn_off", (
            "защита зимой обязана именно выключать: кондиционер, работающий на "
            "холод при отрицательной температуре, повреждается"
        )

    def test_cooling_without_comfort_max_returns_none(self) -> None:
        """Без потолка комфорта охлаждать не к чему — команда не создаётся.

        Returns:
            Ничего.
        """
        action = _action("ac_cool_on")

        assert action(None, _ctx(entity_id="climate.x")) is None, (
            "без comfort_max платформа отправила бы температуру в HA наугад"
        )
