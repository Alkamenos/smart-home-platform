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


class _State:
    """Состояние автомата для заглушки движка."""

    def __init__(self, current_state: str) -> None:
        self.current_state = current_state


class _Engine:
    """Движок-заглушка: помнит подтверждения по автоматам."""

    def __init__(
        self,
        entities: list[str],
        devices: dict[str, str] | None = None,
        states: dict[str, str] | None = None,
    ) -> None:
        self._entities = entities
        self._devices = devices or {}
        #: Состояние автомата; по умолчанию «в работе» — как у вентиляции в AIRING.
        self._states = states or {}
        self.confirmed: list[str] = []
        self.contexts: list[dict[str, Any] | None] = []

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Вернуть автоматы, объявившие событие.

        Args:
            trigger: Имя события.

        Returns:
            Список идентификаторов автоматов.
        """
        assert trigger == "settings_changed"
        return list(self._entities)

    def get_state(self, entity_id: str) -> _State | None:
        """Вернуть состояние автомата.

        Args:
            entity_id: Автомат.

        Returns:
            Состояние либо ``None``, если автомата нет.
        """
        if entity_id not in self._entities:
            return None
        return _State(self._states.get(entity_id, "AIRING"))

    def device_id_of(self, entity_id: str) -> str | None:
        """Вернуть прибор автомата.

        Args:
            entity_id: Автомат.

        Returns:
            Идентификатор прибора либо ``None``.
        """
        return self._devices.get(entity_id)

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        respect_debounce: bool = True,
    ) -> None:
        """Запомнить подтверждение.

        Args:
            entity_id: Автомат.
            event: Событие.
            external_ctx: Внешний контекст перехода.
            respect_debounce: Флаг дебаунса (не используется).
        """
        assert event == "settings_changed"
        self.confirmed.append(entity_id)
        self.contexts.append(external_ctx)


class _Adapter:
    """Адаптер-заглушка: отдаёт заранее заданное состояние прибора."""

    def __init__(self, state: str | None = "on", error: Exception | None = None) -> None:
        self._state = state
        self._error = error
        self.reads: list[str] = []

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Прочитать состояние прибора.

        Args:
            entity_id: Идентификатор прибора.

        Returns:
            Состояние либо ``None``.

        Raises:
            Exception: Если задана ошибка чтения.
        """
        self.reads.append(entity_id)
        if self._error is not None:
            raise self._error
        return self._state


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


class TestStoppedDevice:
    """Остановленный прибор сторож замечает и сообщает автомату (B54)."""

    @pytest.mark.asyncio
    async def test_stopped_device_is_reported(self) -> None:
        """Прибор `off` — автомат получает одноразовый признак остановки.

        Returns:
            Ничего.
        """
        engine = _Engine(
            ["fan.base_smart_ventilation_modes_10"],
            devices={"fan.base_smart_ventilation_modes_10": "fan.base_smart"},
        )
        adapter = _Adapter(state="off")
        watchdog = VentilationWatchdog(engine=engine, adapter=adapter)  # type: ignore[arg-type]

        await watchdog.check_once()

        assert adapter.reads == ["fan.base_smart"], "состояние прибора не прочитано"
        assert engine.contexts == [{"_device_is_off": True}], (
            "автомат не узнал, что прибор остановлен: подтверждение уйдёт одним "
            "режимом, и рекуператор не поднимется (B54)"
        )

    @pytest.mark.asyncio
    async def test_running_device_is_not_reported(self) -> None:
        """Работающий прибор — обычное подтверждение, без признака остановки.

        Returns:
            Ничего.
        """
        engine = _Engine(
            ["fan.base_smart_ventilation_modes_10"],
            devices={"fan.base_smart_ventilation_modes_10": "fan.base_smart"},
        )
        watchdog = VentilationWatchdog(engine=engine, adapter=_Adapter(state="on"))  # type: ignore[arg-type]

        await watchdog.check_once()

        assert engine.contexts == [None], (
            "работающему прибору шлётся признак остановки: подтверждение снова "
            "пошлёт включение с процентом"
        )

    @pytest.mark.asyncio
    async def test_read_failure_is_silent(self) -> None:
        """Неудача чтения — обычное подтверждение, без признака остановки.

        Returns:
            Ничего.
        """
        engine = _Engine(
            ["fan.base_smart_ventilation_modes_10"],
            devices={"fan.base_smart_ventilation_modes_10": "fan.base_smart"},
        )
        adapter = _Adapter(error=RuntimeError("нет связи"))
        watchdog = VentilationWatchdog(engine=engine, adapter=adapter)  # type: ignore[arg-type]

        await watchdog.check_once()

        assert engine.contexts == [None], (
            "молчание прибора принято за остановку: команда ушла бы наугад"
        )

    @pytest.mark.asyncio
    async def test_idle_automaton_is_not_disturbed(self) -> None:
        """Стоящему автомату остановленный прибор — норма, признак не шлётся.

        Returns:
            Ничего.
        """
        engine = _Engine(
            ["fan.vykliuchatel_sanuzel_switch2_ventilation_modes_10"],
            devices={
                "fan.vykliuchatel_sanuzel_switch2_ventilation_modes_10": (
                    "fan.vykliuchatel_sanuzel_switch2"
                )
            },
            states={"fan.vykliuchatel_sanuzel_switch2_ventilation_modes_10": "IDLE"},
        )
        adapter = _Adapter(state="off")
        watchdog = VentilationWatchdog(engine=engine, adapter=adapter)  # type: ignore[arg-type]

        await watchdog.check_once()

        assert engine.contexts == [None], (
            "стоящему автомату шлётся признак остановки: он подтвердил бы решение "
            "включением прибора, которому положено стоять"
        )
        assert adapter.reads == [], "состояние прибора читается даже для IDLE"


def test_engine_type_is_used() -> None:
    """Заглушка совместима по аннотации с FSMEngine.

    Returns:
        Ничего.
    """
    engine: Any = FSMEngine()
    watchdog = VentilationWatchdog(engine=engine)
    assert watchdog.engine is engine
