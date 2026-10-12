"""Сторож вентиляции подтверждает решение автоматов по времени (спека 014).

Рекуператор может «соскочить» с заданного режима между событиями датчика: в бою
2026-10-13 платформа отправляла «Приток MAX», а через пару минут прибор снова
стоял на «Рекуперации (зиме)». Сторож закрывает дыру: раз в интервал шлёт
автоматам вентиляции `settings_changed` — тот же путь, что и смена флагов дома.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.fsm.engine import FSMEngine
from core.services.ventilation_watchdog import VentilationWatchdog


class _Engine:
    """Движок-заглушка: помнит подтверждения по автоматам."""

    def __init__(self, entities: list[str]) -> None:
        self._entities = entities
        self.confirmed: list[str] = []

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Вернуть автоматы, объявившие событие.

        Args:
            trigger: Имя события.

        Returns:
            Список идентификаторов автоматов.
        """
        assert trigger == "settings_changed"
        return list(self._entities)

    async def trigger(self, entity_id: str, event: str, respect_debounce: bool = True) -> None:
        """Запомнить подтверждение.

        Args:
            entity_id: Автомат.
            event: Событие.
            respect_debounce: Флаг дебаунса (не используется).
        """
        assert event == "settings_changed"
        self.confirmed.append(entity_id)


class TestVentilationWatchdog:
    """Сторож подтверждает решение только у автоматов вентиляции."""

    @pytest.mark.asyncio
    async def test_confirms_only_ventilation_automata(self) -> None:
        """Шторы и свет сторож не трогает, вентиляцию — подтверждает.

        Returns:
            Ничего.
        """
        engine = _Engine(
            [
                "fan.base_smart_ventilation_modes_10",
                "cover.shtora_v_spalne_cover_modes_10",
                "light.table_lights_lighting_10",
            ]
        )
        watchdog = VentilationWatchdog(engine=engine, interval_minutes=5.0)  # type: ignore[arg-type]

        await watchdog.check_once()

        assert engine.confirmed == ["fan.base_smart_ventilation_modes_10"]

    def test_describe_reports_interval(self) -> None:
        """Описание содержит интервал и признак работы.

        Returns:
            Ничего.
        """
        engine = _Engine([])
        watchdog = VentilationWatchdog(engine=engine, interval_minutes=2.0)  # type: ignore[arg-type]

        described = watchdog.describe()

        assert described["interval_minutes"] == 2.0
        assert described["running"] is False


def test_engine_type_is_used() -> None:
    """Заглушка совместима по аннотации с FSMEngine.

    Returns:
        Ничего.
    """
    engine: Any = FSMEngine()
    watchdog = VentilationWatchdog(engine=engine)
    assert watchdog.engine is engine
