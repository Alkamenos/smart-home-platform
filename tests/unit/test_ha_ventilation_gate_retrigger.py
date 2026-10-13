"""Переключатели вентиляции действуют немедленно (боевой разбор 2026-10-12).

Автомат вентиляции ждёт показания температуры: его переходы объявлены по
`temperature_changed`. Выключатель владельца, фиче-флаг дома, сезон и модификаторы
проветривания/вытяжки живут в Home Assistant и приходят не от датчика. Пока датчик
молчал, выключение вентиляции не действовало: в бою 2026-10-12 рекуператор
продолжал дуть сырым притоком на 91 % более часа после того, как владелец выключил
`input_boolean.ventiliatsiia`.

Проверка идёт на настоящем `HAAdapter` с подменённым клиентом и роутером: нас
интересует, что смена глобального переключателя доносится до роутера (он один
знает комнату и климат-автоматы и кладёт в контекст `heating_active`), а обычное
событие датчика этим путём не идёт.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.ha_adapter import HAAdapter


class _Client:
    """Клиент Home Assistant с ролями глобальных сущностей и их значениями."""

    daylight = True
    asleep = False

    def __init__(self) -> None:
        self.ventilation_on: bool | None = None
        #: Числовые переключатели: порог «жарко» и уставка комнаты.
        self.comfort_max: float | None = None
        self.climate_setpoint: float | None = None

    def global_role(self, entity: str) -> str | None:
        """Роль глобальной сущности по её идентификатору.

        Args:
            entity: Идентификатор сущности.

        Returns:
            Роль либо ``None``, если сущность не глобальная.
        """
        return {
            "input_boolean.ventiliatsiia": "enable",
            "input_boolean.feature_ventilation": "ventilation_feature",
            "input_boolean.zima": "season",
            "input_boolean.provetrivanie": "airing",
            "input_boolean.provetrivanie_vytyazhka": "exhaust",
            "input_number.maksimalno_komfortnaia_temperatura": "comfort_max",
            "input_number.temperatura": "setpoint",
            "sensor.datchik_temperatury_kabinet_temperature": None,
        }.get(entity)


def _build() -> tuple[HAAdapter, AsyncMock, _Client]:
    """Адаптер без сети с подменённым роутером и клиентом с ролями.

    Returns:
        Адаптер, роутер-заглушка и клиент.
    """
    router = MagicMock()
    router.route_settings_change = AsyncMock()
    adapter = HAAdapter(mode="pyscript", engine=MagicMock(), hass=MagicMock(), event_router=router)
    client = _Client()
    adapter._ws_client = client  # type: ignore[assignment]
    return adapter, router.route_settings_change, client


@pytest.mark.asyncio
async def test_turning_off_owner_switch_reevaluates_ventilation_immediately() -> None:
    """Выключение вентиляции владельцем доносится до роутера сразу.

    Returns:
        Ничего.
    """
    adapter, route, client = _build()
    client.ventilation_on = False

    await adapter.on_state_change("input_boolean.ventiliatsiia", "off", "on", {})

    route.assert_awaited_once()
    context: dict[str, Any] = route.await_args.args[0]
    assert context["ventilation_on"] is False, (
        "роутер получил старое значение: пересмотр решит по старой воле владельца"
    )


@pytest.mark.asyncio
async def test_season_modifier_reevaluates_ventilation() -> None:
    """Смена сезона — тоже переключатель вентиляции (режим зима/лето).

    Returns:
        Ничего.
    """
    adapter, route, _ = _build()

    await adapter.on_state_change("input_boolean.zima", "off", "on", {})

    route.assert_awaited_once()


@pytest.mark.asyncio
async def test_comfort_max_change_reevaluates_ventilation_immediately() -> None:
    """Смена потолка комфорта пересматривает вентиляцию сразу (B42).

    Returns:
        Ничего.
    """
    adapter, route, client = _build()
    client.comfort_max = 23.0

    await adapter.on_state_change(
        "input_number.maksimalno_komfortnaia_temperatura", "23.0", "25.0", {}
    )

    route.assert_awaited_once()
    context: dict[str, Any] = route.await_args.args[0]
    assert context["comfort_max"] == 23.0, (
        "роутер получил старый потолок комфорта: правило «жарко» решит по "
        "прежнему порогу и приток включится не тогда, когда нужно"
    )


@pytest.mark.asyncio
async def test_setpoint_change_reevaluates_ventilation_immediately() -> None:
    """Смена уставки комнаты пересматривает вентиляцию сразу (B42).

    Returns:
        Ничего.
    """
    adapter, route, client = _build()
    client.climate_setpoint = 22.0

    await adapter.on_state_change("input_number.temperatura", "22.0", "22.5", {})

    route.assert_awaited_once()
    context: dict[str, Any] = route.await_args.args[0]
    assert context["climate_setpoint"] == 22.0, (
        "роутер получил старую уставку: правило «вентиляция стоит ниже уставки» "
        "(FR-049) решит по прежней цели"
    )


@pytest.mark.asyncio
async def test_startup_reapply_only_on_first_connect() -> None:
    """Признак запуска ставится один раз, при переподключении — уже нет.

    Returns:
        Ничего.
    """
    adapter, route, _ = _build()

    await adapter._route_settings_change_if_possible()
    await adapter._route_settings_change_if_possible()

    first: dict[str, Any] = route.await_args_list[0].args[0]
    second: dict[str, Any] = route.await_args_list[1].args[0]
    assert first["_startup_reapply"] is True, (
        "первый пересмотр не помечен как запуск: восстановленный «Приток MAX» "
        "не включит прибор (B43)"
    )
    assert second["_startup_reapply"] is False, (
        "при переподключении снова шлётся включение с процентом: оно сбрасывает "
        "режим прибора (боевой разбор 2026-10-13)"
    )


@pytest.mark.asyncio
async def test_sensor_event_does_not_retrigger_ventilation() -> None:
    """Обычное событие датчика идёт своим путём, а не через пересмотр.

    Returns:
        Ничего.
    """
    adapter, route, _ = _build()

    await adapter.on_state_change(
        "sensor.datchik_temperatury_kabinet_temperature", "20.9", "20.7", {}
    )

    route.assert_not_awaited()
