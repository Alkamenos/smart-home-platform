"""Сторож сообщает автомату света правду о приборе (B89).

Повтор решения запрещён, когда команды от нас не было: прибор изменил кто-то
другой, и спорить с ним хуже, чем оставить расхождение (B86). Но оставлять
модель в неправде тоже нельзя — иначе свет, погашенный вне платформы, не
включится по движению никогда (боевой разбор 2026-10-17, гостиная).

Здесь проверяется вторая половина правила: вместо повтора автомату уходит
одноразовый признак «прибор не работает», и шаблон приводит модель в
соответствие. Признак адресован лампам и шторам: у вентиляции свой сторож,
который и сообщает факт (B54), и два источника одного признака давали бы двойной
вход в «Приток MAX».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from core.metrics import MetricsCollector
from services.watchdog import MISMATCH_DEVICE_OFF_DECISION_ON, WatchdogService, WatchdogSettings


#: Автомат света и его прибор.
LIGHT_FSM = "light.stol_lighting_10"
LIGHT_DEVICE = "light.stol"

#: Автомат шторы и её прибор — «прибор не работает» у шторы значит `closed`.
COVER_FSM = "cover.shtora_cover_modes_10"
COVER_DEVICE = "cover.shtora"

#: Автомат вентиляции и её прибор — у вентиляции свой сторож (B54).
FAN_FSM = "fan.rekuperator_ventilation_modes_10"
FAN_DEVICE = "fan.rekuperator"

#: Событие сторожа о расхождении прибора и решения.
DIVERGED = "device_state_diverged"


@dataclass
class _Engine:
    """Движок ровно с тем, что спрашивает сторож, и с записью контекста.

    Attributes:
        states: Автомат → текущее состояние.
        devices: Автомат → сущность прибора.
        outcomes: Автомат → исход последнего решения.
        triggered: Записанные вызовы: (автомат, событие, контекст).
    """

    states: dict[str, str]
    devices: dict[str, str]
    outcomes: dict[str, str | None] = field(default_factory=dict)
    triggered: list[tuple[str, str, dict[str, Any] | None]] = field(default_factory=list)

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        respect_debounce: bool = True,
        trace_id: str | None = None,
    ) -> bool:
        """Запомнить вызов вместе с контекстом.

        Args:
            entity_id: Автомат.
            event: Событие.
            external_ctx: Внешний контекст — здесь живёт признак прибора.
            respect_debounce: Флаг дебаунса.
            trace_id: Идентификатор трассы.

        Returns:
            True — вызов принят.
        """
        del trace_id
        assert respect_debounce is False, "событие сторожа не должно ждать дебаунса"
        self.triggered.append((entity_id, event, external_ctx))
        return True

    def get_all_states(self) -> dict[str, Any]:
        """Состояния всех автоматов.

        Returns:
            Автомат → снимок состояния.
        """
        now = time.monotonic()
        return {
            entity_id: SimpleNamespace(current_state=state, entered_at=now, context={})
            for entity_id, state in self.states.items()
        }

    def expected_timeout_sec(self, entity_id: str) -> float | None:
        """Зависание не проверяется: оно не предмет этого теста.

        Args:
            entity_id: Автомат.

        Returns:
            Всегда None.
        """
        del entity_id
        return None

    def device_id_of(self, entity_id: str) -> str | None:
        """Сущность прибора автомата.

        Args:
            entity_id: Автомат.

        Returns:
            Сущность прибора либо None.
        """
        return self.devices.get(entity_id)

    def get_last_transition_time(self, entity_id: str) -> str | None:
        """Время последнего перехода неизвестно.

        Args:
            entity_id: Автомат.

        Returns:
            Всегда None.
        """
        del entity_id
        return None

    def explain(self, entity_id: str) -> Any | None:
        """Последнее решение автомата.

        Args:
            entity_id: Автомат.

        Returns:
            Решение либо None.
        """
        outcome = self.outcomes.get(entity_id)
        if outcome is None:
            return None
        return SimpleNamespace(outcome=outcome)


@dataclass
class _Adapter:
    """Внешняя система: состояния приборов задаются тестом.

    Attributes:
        device_states: Сущность → состояние.
    """

    device_states: dict[str, str | None] = field(default_factory=dict)

    is_connected = True

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Состояния всех сущностей.

        Returns:
            Список состояний.
        """
        return []

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Прочитать состояние прибора.

        Args:
            entity_id: Сущность прибора.

        Returns:
            Состояние либо None.
        """
        return self.device_states.get(entity_id)


def _watchdog(engine: _Engine, adapter: _Adapter, commanded: bool = False) -> WatchdogService:
    """Собрать сторож с подменёнными движком и внешней системой.

    Args:
        engine: Движок-двойник.
        adapter: Внешняя система-двойник.
        commanded: Считаем ли, что прибору приказывали мы.

    Returns:
        Сторож.
    """
    return WatchdogService(
        fsm_engine=engine,  # type: ignore[arg-type]
        metrics=MetricsCollector(registry=CollectorRegistry()),
        adapter=adapter,  # type: ignore[arg-type]
        settings=WatchdogSettings(interval_sec=0.01),
        command_recency_supplier=lambda _device: commanded,
    )


class TestDeviceTruthIsSentToLights:
    """Расхождение без нашей команды: правда о приборе уходит автомату света."""

    @pytest.mark.asyncio
    async def test_light_is_told_the_device_is_off(self) -> None:
        """Автомат света получает одноразовый признак «прибор выключен»."""
        engine = _Engine({LIGHT_FSM: "ON_HOLD"}, {LIGHT_FSM: LIGHT_DEVICE})
        adapter = _Adapter({LIGHT_DEVICE: "off"})

        snapshot = await _watchdog(engine, adapter).check_once()
        assert snapshot.entries[0].mismatch_reason == MISMATCH_DEVICE_OFF_DECISION_ON
        assert engine.triggered == [(LIGHT_FSM, DIVERGED, {"_device_is_off": True})], (
            "автомат света не получил правду о приборе: движение в «горит» команду "
            "не шлёт, повтор запрещён — свет не включится никогда"
        )

    @pytest.mark.asyncio
    async def test_repeat_stays_when_the_command_was_ours(self) -> None:
        """Наша команда не применилась — поведение прежнее: решение повторяется."""
        engine = _Engine({LIGHT_FSM: "ON_HOLD"}, {LIGHT_FSM: LIGHT_DEVICE})
        adapter = _Adapter({LIGHT_DEVICE: "off"})

        await _watchdog(engine, adapter, commanded=True).check_once()

        assert engine.triggered == [(LIGHT_FSM, DIVERGED, None)], (
            "повтор решения обязан идти без признака: иначе автомат уступал бы "
            "прибору там, где прибор должен был послушаться нас"
        )

    @pytest.mark.asyncio
    async def test_cover_is_told_too(self) -> None:
        """Шторе факт уходит: «прибор не работает» у неё — это `closed`.

        Словарь расхождений у лампы и шторы общий (`device_off_decision_on`),
        поэтому признак адресован обоим семействам, а что он значит — решает
        шаблон. Боевой разбор 2026-10-17: штора спальни стояла в расхождении
        «автомат `OPEN`, прибор `closed`».
        """
        engine = _Engine({COVER_FSM: "OPEN"}, {COVER_FSM: COVER_DEVICE})
        adapter = _Adapter({COVER_DEVICE: "closed"})

        await _watchdog(engine, adapter).check_once()

        assert engine.triggered == [(COVER_FSM, DIVERGED, {"_device_is_off": True})], (
            "штора осталась в расхождении: модель считает её открытой, а правила "
            "на смену флагов дома ничего не пересмотрят"
        )

    @pytest.mark.asyncio
    async def test_fan_is_left_to_its_own_watchdog(self) -> None:
        """Вентиляция не здесь: у неё свой сторож, который и сообщает факт (B54)."""
        engine = _Engine({FAN_FSM: "AIRING"}, {FAN_FSM: FAN_DEVICE})
        adapter = _Adapter({FAN_DEVICE: "off"})

        await _watchdog(engine, adapter).check_once()

        assert engine.triggered == [], (
            "вентиляцию тронул общий сторож: у неё свой, и два источника одного "
            "признака давали бы двойной вход в «Приток MAX»"
        )

    @pytest.mark.asyncio
    async def test_unreadable_device_is_not_guessed(self) -> None:
        """Прибор не прочитался — правду не выдумываем."""
        engine = _Engine({LIGHT_FSM: "ON_HOLD"}, {LIGHT_FSM: LIGHT_DEVICE})
        adapter = _Adapter({})  # состояния нет

        await _watchdog(engine, adapter).check_once()

        assert engine.triggered == [], "молчание прибора выдано за «выключен»"
