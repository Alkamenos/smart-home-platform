"""Атрибутная команда не проигрывает занятому прибору.

Боевая находка 2026-10-23: глобальная цветовая температура каждые пять минут
отклонялась с записью «Ignored light_color_temperature (10) because websocket
(50) is active». Включение света оставляет намерение на час, и температура не
применялась вовсе — владелец видел, что оттенок не меняется.

Температура не включает и не выключает лампу, а подправляет оттенок горящей.
Поэтому у неё отдельный путь: она не участвует в приоритетной очереди, не
удерживает устройство и не снимает чужое намерение. Ручная блокировка при этом
остаётся: её отсекает посредник до этой ветки.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.commands.dispatcher import CommandDispatcher, CommandIntent


class _Adapter:
    """Адаптер, запоминающий вызовы вместо обращения в Home Assistant."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Запомнить вызов."""
        self.calls.append(
            {
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "data": data or {},
            }
        )
        return True

    async def get_state(self, entity_id: str) -> str | None:
        """Состояние не читается — команде оно и не нужно."""
        return None


def _intent(**overrides: Any) -> CommandIntent:
    """Команда температуры по умолчанию.

    Args:
        overrides: Поля, которые нужно заменить.

    Returns:
        Готовая команда.
    """
    data: dict[str, Any] = {
        "device_id": "light.svet_nad_stolom",
        "domain": "light",
        "service": "turn_on",
        "data": {"color_temp_kelvin": 2700},
        "priority": 10,
        "source": "light_color_temperature",
        "conflict_free": True,
    }
    data.update(overrides)
    return CommandIntent(**data)


class TestAttributeIntentDoesNotLoseToPriority:
    """Коррекция атрибута проходит мимо захвата устройства."""

    async def test_applies_when_device_is_captured_by_higher_priority(self) -> None:
        """Прибор занят намерением websocket (50) — температура всё равно уходит."""
        adapter = _Adapter()
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        held = _intent(
            conflict_free=False,
            priority=50,
            source="websocket",
            data={"brightness_pct": 100},
        )
        assert await dispatcher.submit(held) is True
        adapter.calls.clear()

        assert await dispatcher.submit(_intent()) is True

        assert adapter.calls, "температура не дошла до Home Assistant при занятом приборе"
        assert adapter.calls[0]["data"] == {"color_temp_kelvin": 2700}

    async def test_does_not_capture_device_after_itself(self) -> None:
        """Атрибутная команда не оставляет захвата: следующая команда света идёт."""
        adapter = _Adapter()
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        assert await dispatcher.submit(_intent()) is True
        adapter.calls.clear()

        light_on = _intent(
            conflict_free=False,
            priority=10,
            source="lighting",
            service="turn_on",
            data={"brightness_pct": 100},
        )
        assert await dispatcher.submit(light_on) is True
        assert adapter.calls, "включение света не прошло после коррекции температуры"
