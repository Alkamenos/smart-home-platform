"""Пересмотр по смене настройки видит последние показания (спека 017, FR-027).

Регресс 2026-10-14: `settings_changed` (выключатель владельца, сезон, флаг дома)
приходил без значений датчиков, и условия вентиляции отказывали
`guard_data_missing` — решение владельца не доходило до автомата. Тест держит
подстановку последних измерений в контекст пересмотра.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.events.event_router import EventRouter
from core.models.manifest import (
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)


FSM_ID = "fan.spalnia_ventilation_modes_10"


class _Engine:
    """Движок-двойник: один автомат вентиляции, запоминает контексты триггеров."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Автоматы устройства.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            Список идентификаторов автоматов.
        """
        return [FSM_ID] if device_id == "fan.spalnia" else []

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Автоматы, слушающие триггер.

        Args:
            trigger: Имя триггера.

        Returns:
            Список автоматов.
        """
        return [FSM_ID]

    def get_state(self, entity_id: str) -> None:
        """Состояние автомата (не нужно тесту)."""
        return None

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> bool:
        """Запомнить контекст триггера.

        Args:
            entity_id: Автомат.
            event: Событие.
            external_ctx: Контекст.
            kwargs: Прочие параметры.

        Returns:
            True.
        """
        self.calls.append({"event": event, "ctx": dict(external_ctx or {})})
        return True


def _router() -> tuple[EventRouter, _Engine]:
    """Маршрутизатор с одной комнатой и датчиками температуры и влажности.

    Returns:
        Маршрутизатор и движок-двойник.
    """
    manifest = Manifest(
        instance=InstanceConfig(id="p", name="P", owner="p", created_at=""),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={
                    "temperature": "sensor.t",
                    "humidity": "sensor.h",
                },
                devices=[
                    DeviceConfig(
                        id="fan.spalnia",
                        type="fan",
                        behaviors=[BehaviorConfig(template="ventilation_modes", priority=10)],
                    )
                ],
            )
        ],
    )
    engine = _Engine()
    return EventRouter(manifest, engine), engine


@pytest.mark.asyncio
async def test_settings_change_should_carry_last_measurements() -> None:
    """Смена настройки несёт последние температуру и влажность комнаты."""
    router, engine = _router()
    await router.route_state_change("sensor.t", "24.5", "24.0")
    await router.route_state_change("sensor.h", "55", "54")
    engine.calls.clear()

    await router.route_settings_change({})

    assert engine.calls, "пересмотр не дошёл до автомата"
    ctx = engine.calls[0]["ctx"]
    assert ctx["temperature"] == 24.5
    assert ctx["humidity"] == 55.0


@pytest.mark.asyncio
async def test_settings_change_should_not_invent_missing_measurements() -> None:
    """Без показаний ничего не выдумывается — ключей просто нет."""
    router, engine = _router()

    await router.route_settings_change({})

    assert engine.calls
    ctx = engine.calls[0]["ctx"]
    assert "temperature" not in ctx
    assert "humidity" not in ctx
