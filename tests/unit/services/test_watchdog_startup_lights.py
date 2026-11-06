"""Стартовая сверка света: лампа после появления питания гасится (T058).

После возврата питания Home Assistant присылает «лампа горит» без действия
человека. Обычная проверка сторожа уступает ручной блокировке, и свет остаётся
гореть. Первая проверка после запуска платформы должна снять блокировку с лампы
и повторить решение автомата «выключено».

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
from services.watchdog import (
    MISMATCH_DEVICE_ON_DECISION_OFF,
    MISMATCH_MANUAL_OVERRIDE,
    WatchdogService,
    WatchdogSettings,
)


LIGHT_FSM = "light.stol_lighting_10"
LIGHT_DEVICE = "light.stol"
SWITCH_LIGHT_FSM = "switch.podsvetka_zerkala_deco_light_10"
SWITCH_LIGHT_DEVICE = "switch.podsvetka_zerkala"
COVER_FSM = "cover.shtora_cover_modes_10"
COVER_DEVICE = "cover.shtora"
DIVERGED = "device_state_diverged"


@dataclass
class _Engine:
    """Движок ровно с тем, что спрашивает сторож."""

    states: dict[str, str]
    devices: dict[str, str]
    triggered: list[tuple[str, str, dict[str, Any] | None]] = field(default_factory=list)

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        respect_debounce: bool = True,
        trace_id: str | None = None,
    ) -> bool:
        """Запомнить вызов сторожа."""
        del trace_id
        assert respect_debounce is False
        self.triggered.append((entity_id, event, external_ctx))
        return True

    def get_all_states(self) -> dict[str, Any]:
        """Состояния всех автоматов."""
        now = time.monotonic()
        return {
            entity_id: SimpleNamespace(current_state=state, entered_at=now, context={})
            for entity_id, state in self.states.items()
        }

    def expected_timeout_sec(self, entity_id: str) -> float | None:
        """Зависание не проверяется."""
        del entity_id
        return None

    def device_id_of(self, entity_id: str) -> str | None:
        """Сущность прибора автомата."""
        return self.devices.get(entity_id)

    def get_last_transition_time(self, entity_id: str) -> str | None:
        """Время последнего перехода неизвестно."""
        del entity_id
        return None

    def explain(self, entity_id: str) -> Any | None:
        """Последнее решение не задано: состояние называет его само."""
        del entity_id
        return None


@dataclass
class _Adapter:
    """Внешняя система: состояния приборов задаются тестом."""

    device_states: dict[str, str | None] = field(default_factory=dict)
    is_connected = True

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Массовое чтение не нужно: сторож прочитает поштучно."""
        return []

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Состояние прибора."""
        return self.device_states.get(entity_id)


def _watchdog(
    engine: _Engine,
    adapter: _Adapter,
    *,
    manual_override: bool = True,
    off_calls: list[str] | None = None,
) -> WatchdogService:
    """Собрать сторожа с активной ручной блокировкой и записью выключений."""
    off_calls = off_calls if off_calls is not None else []

    async def _turn_off(device_id: str) -> None:
        off_calls.append(device_id)

    return WatchdogService(
        fsm_engine=engine,  # type: ignore[arg-type]
        metrics=MetricsCollector(registry=CollectorRegistry()),
        adapter=adapter,  # type: ignore[arg-type]
        settings=WatchdogSettings(interval_sec=0.01),
        manual_override_supplier=lambda _device: manual_override,
        startup_light_off=_turn_off,
        command_recency_supplier=lambda _device: False,
    )


class TestStartupLightCleanup:
    """Стартовая проверка гасит лампу, включившуюся от питания."""

    @pytest.mark.asyncio
    async def test_startup_clears_lockout_and_repeats_off(self) -> None:
        """Лампа горит, решение — выключено: блокировка снята, решение повторено."""
        engine = _Engine({LIGHT_FSM: "OFF"}, {LIGHT_FSM: LIGHT_DEVICE})
        adapter = _Adapter({LIGHT_DEVICE: "on"})
        off_calls: list[str] = []

        snapshot = await _watchdog(engine, adapter, off_calls=off_calls).check_once(startup=True)

        assert snapshot.entries[0].mismatch_reason == MISMATCH_DEVICE_ON_DECISION_OFF
        assert off_calls == [LIGHT_DEVICE], "стартовая сверка не погасила лампу"
        assert engine.triggered == [], "команда выключения должна идти напрямую"

    @pytest.mark.asyncio
    async def test_startup_clears_switch_based_light(self) -> None:
        """Подсветка зеркала — домен switch, но шаблон света: её тоже гасим."""
        engine = _Engine({SWITCH_LIGHT_FSM: "OFF"}, {SWITCH_LIGHT_FSM: SWITCH_LIGHT_DEVICE})
        adapter = _Adapter({SWITCH_LIGHT_DEVICE: "on"})
        off_calls: list[str] = []

        await _watchdog(engine, adapter, off_calls=off_calls).check_once(startup=True)

        assert off_calls == [SWITCH_LIGHT_DEVICE]

    @pytest.mark.asyncio
    async def test_regular_check_still_respects_manual_override(self) -> None:
        """Обычная проверка не спорит с человеком и блокировку не снимает."""
        engine = _Engine({LIGHT_FSM: "OFF"}, {LIGHT_FSM: LIGHT_DEVICE})
        adapter = _Adapter({LIGHT_DEVICE: "on"})
        off_calls: list[str] = []

        snapshot = await _watchdog(engine, adapter, off_calls=off_calls).check_once()

        assert snapshot.entries[0].mismatch_reason == MISMATCH_MANUAL_OVERRIDE
        assert off_calls == []
        assert engine.triggered == []

    @pytest.mark.asyncio
    async def test_startup_does_not_clear_non_light_devices(self) -> None:
        """Штору стартовая сверка не трогает: правило только про лампы."""
        engine = _Engine({COVER_FSM: "CLOSED"}, {COVER_FSM: COVER_DEVICE})
        adapter = _Adapter({COVER_DEVICE: "open"})
        off_calls: list[str] = []

        snapshot = await _watchdog(engine, adapter, off_calls=off_calls).check_once(startup=True)

        assert snapshot.entries[0].mismatch_reason == MISMATCH_MANUAL_OVERRIDE
        assert off_calls == []
        assert engine.triggered == [(COVER_FSM, DIVERGED, {"_device_is_on": True})], (
            "штора получает правду о приборе, но стартовая сверка её не гасит"
        )
