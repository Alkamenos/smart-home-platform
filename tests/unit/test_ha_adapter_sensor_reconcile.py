"""Сверка датчиков при подключении (B40, спека 014).

Home Assistant присылает событие только при изменении, поэтому после перезапуска
платформы молчащий датчик не попадает в контекст автомата: тот живёт со значением,
восстановленным из сохранённого состояния. В бою 2026-10-12 рекуператор спальни
работал физически, а автомат считал `IDLE`, потому что датчик не менялся больше
часа. Адаптер обязан один раз прочитать текущие показания и провести их тем же
путём, что и настоящее событие.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter


class _Router:
    """Роутер-заглушка: помнит разосланные показания."""

    def __init__(self, sensors: list[str]) -> None:
        self._sensors = sensors
        self.routed: list[dict[str, Any]] = []

    def mapped_sensors(self) -> list[str]:
        """Вернуть датчики, известные роутеру.

        Returns:
            Список идентификаторов.
        """
        return list(self._sensors)

    async def route_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Запомнить разосланное показание.

        Args:
            entity_id: Датчик.
            new_state: Новое состояние.
            old_state: Прежнее состояние.
            context: Контекст события.
        """
        self.routed.append(
            {
                "entity_id": entity_id,
                "new_state": new_state,
                "old_state": old_state,
                "context": context or {},
            }
        )


def _adapter(router: Any, states: dict[str, str | None]) -> HAAdapter:
    """Адаптер с заглушкой роутера и заданными состояниями датчиков.

    Args:
        router: Роутер (настоящий или заглушка).
        states: Состояния по имени датчика.

    Returns:
        Настроенный адаптер.
    """
    adapter = HAAdapter(
        mode="websocket",
        ws_url="ws://localhost:8123",
        token="t",
        event_router=router,
    )

    async def fake_read(entity: str) -> str | None:
        """Вернуть заданное состояние датчика.

        Args:
            entity: Датчик.

        Returns:
            Состояние либо None.
        """
        return states.get(entity)

    adapter._read_entity_state = fake_read  # type: ignore[method-assign]
    return adapter


class TestSensorReconcile:
    """Показания датчиков читаются при подключении и доходят до автоматов."""

    @pytest.mark.asyncio
    async def test_all_mapped_sensors_are_routed(self) -> None:
        """Каждый известный датчик рассылается со своим текущим показанием.

        Returns:
            Ничего.
        """
        router = _Router(["sensor.a", "sensor.b"])
        adapter = _adapter(router, {"sensor.a": "23.5", "sensor.b": "off"})

        await adapter._reconcile_sensor_states()  # noqa: SLF001

        assert [call["entity_id"] for call in router.routed] == ["sensor.a", "sensor.b"]
        assert router.routed[0]["new_state"] == "23.5"
        assert router.routed[0]["old_state"] == "23.5", (
            "при сверке прежнего значения нет: новое и прежнее совпадают"
        )

    @pytest.mark.asyncio
    async def test_unavailable_sensor_is_skipped(self) -> None:
        """Датчик без состояния не рассылается и не роняет сверку.

        Returns:
            Ничего.
        """
        router = _Router(["sensor.a", "sensor.b"])
        adapter = _adapter(router, {"sensor.a": "23.5", "sensor.b": None})

        await adapter._reconcile_sensor_states()  # noqa: SLF001

        assert [call["entity_id"] for call in router.routed] == ["sensor.a"]

    @pytest.mark.asyncio
    async def test_without_router_is_noop(self) -> None:
        """Без роутера сверка молча ничего не делает.

        Returns:
            Ничего.
        """
        adapter = _adapter(None, {})

        await adapter._reconcile_sensor_states()  # noqa: SLF001
