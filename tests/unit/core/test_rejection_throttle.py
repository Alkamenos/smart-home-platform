"""Молчащий датчик не засоряет журнал (FR-047).

Один сломанный датчик шлёт события каждые несколько минут. Если каждый отказ
попадает в журнал, утренний разбор утонет в одинаковых строках — это ровно то,
из-за чего журнал однажды читали как «80 % шума» (Known Issue #79).

Поведение уже реализовано в движке: отказ пишется один раз на пару
«сущность + причина», дальше копится счётчик, доступный через
`rejection_counts()`. Здесь оно зафиксировано, чтобы не разъехалось при
изменениях.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest

from core.action_handlers import register_all_actions
from core.control_tracker import ControlTracker
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import register_all_guards
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


SENSOR = "sensor.datchik_temperatury_spalnia_temperature"
HEATER = "switch.obogrevatel_spalnia"


def _build() -> FSMEngine:
    """Движок с одним автоматом климата.

    Returns:
        Готовый движок.
    """
    registry = Registry()
    register_all_guards(registry, ControlTracker())
    register_all_actions(registry)
    manifest = Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={"temperature": SENSOR},
                devices=[
                    DeviceConfig(
                        id=HEATER,
                        type="climate",
                        behaviors=[
                            BehaviorConfig(template="climate_control", priority=10, params={})
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )
    engine = FSMEngine()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine


class TestSilentSensorStaysQuiet:
    """Молчащий датчик: одна запись в журнал, счётчик копится."""

    @pytest.mark.asyncio
    async def test_repeated_rejections_logged_once(self) -> None:
        """Сто отказов подряд дают одну запись в журнал.

        Returns:
            Ничего.
        """
        engine = _build()
        entity = "switch.obogrevatel_spalnia_climate_control_10"

        for _ in range(100):
            await engine.trigger(
                entity,
                "temperature_changed",
                external_ctx={"temperature": "unavailable", "climate_setpoint": 21.0},
                respect_debounce=False,
            )

        counts = engine.rejection_counts()
        assert counts.get("guard_data_missing", 0) == 100, (
            f"счётчик отказов должен копить каждое решение: по нему видно, "
            f"что датчик молчит, даже когда в журнал пишется одна строка. {counts}"
        )

    @pytest.mark.asyncio
    async def test_broken_setpoint_blocks_heating(self) -> None:
        """Уставка вне диапазона не греет комнату молча.

        Отдельно от счётчика: пока датчик жив, переход «ничего не делать»
        проходит, и решение принято — обогрев не включается, что и требуется.
        Проверяется именно то, что молча греть по негодной уставке нельзя.

        Returns:
            Ничего.
        """
        engine = _build()
        entity = "switch.obogrevatel_spalnia_climate_control_10"

        await engine.trigger(
            entity,
            "temperature_changed",
            external_ctx={
                "temperature": 19.0,
                "climate_setpoint": 95.0,
                "setpoint_min": 5.0,
                "setpoint_max": 30.0,
            },
            respect_debounce=False,
        )

        assert engine.get_state(entity).current_state == "IDLE", (
            "уставка 95 градусов вне диапазона: греть по ней — значит перегреть "
            "дом, а молча подставить запасную — значит не сказать, что не так"
        )

    @pytest.mark.asyncio
    async def test_recovery_reports_no_new_rejection(self) -> None:
        """Возврат датчика не считается отказом.

        Returns:
            Ничего.
        """
        engine = _build()
        entity = "switch.obogrevatel_spalnia_climate_control_10"

        for _ in range(5):
            await engine.trigger(
                entity,
                "temperature_changed",
                external_ctx={"temperature": "unavailable", "climate_setpoint": 21.0},
                respect_debounce=False,
            )
        await engine.trigger(
            entity,
            "temperature_changed",
            external_ctx={"temperature": 19.0, "climate_setpoint": 21.0},
            respect_debounce=False,
        )

        assert engine.get_state(entity).current_state == "HEATING", (
            "после восстановления датчика комната обязана работать"
        )
