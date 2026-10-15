"""Разовые признаки: без них переход не относится к случаю (BACKLOG B74).

Признаки `_startup_reapply` (первый пересмотр после запуска платформы),
`_device_is_off` и `_device_is_on` (сообщения сторожа вентиляции) ставит платформа
на **одном** событии. На обычном событии их нет — и переход не к этому случаю
вовсе, а не «условие не прошло»: иначе журнал наполнялся бы отказом
`guard_failed` на каждом событии (около 32 записей за ночь, разбор приёмки
2026-10-15).

Движок такие переходы пропускает молча — тем же механизмом, что и «переход к
прибору не относится» (B66): условие называет причину `not_applicable`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.events.event_bus import EventBus
from core.fsm.engine import FSMDefinition, FSMEngine, Transition
from core.guards.builtin import (
    make_device_is_off,
    make_device_is_on,
    make_mode_for_weather,
    make_owner_wants_airing,
    make_should_run_exhaust,
    make_should_run_max_supply,
    make_startup_reapply,
)


def test_startup_reapply_is_not_applicable_without_the_flag() -> None:
    """Обычное событие: пересмотра при запуске не было — переход не к нему."""
    guard = make_startup_reapply()

    assert guard.deny_reason(None, {"room": "sanuzel"}) == "not_applicable"


def test_startup_reapply_applies_to_supply_on_startup() -> None:
    """Первый пересмотр и роль «приток» — переход к случаю."""
    guard = make_startup_reapply()
    context = {"_startup_reapply": True, "ventilation_role": "supply"}

    assert guard.deny_reason(None, context) is None
    assert guard(None, context) is True


def test_startup_reapply_is_not_applicable_for_other_roles() -> None:
    """Первый пересмотр у вытяжки — не тот случай: ей подтверждать нечего."""
    guard = make_startup_reapply()
    context = {"_startup_reapply": True, "ventilation_role": "exhaust"}

    assert guard.deny_reason(None, context) == "not_applicable"


def test_device_is_off_is_not_applicable_without_the_report() -> None:
    """Сторож не сообщал об остановленном приборе — переход не к случаю."""
    guard = make_device_is_off()

    assert guard.deny_reason(None, {}) == "not_applicable"
    assert guard.deny_reason(None, {"_device_is_off": True}) is None


def test_device_is_on_is_not_applicable_without_the_report() -> None:
    """Сторож не сообщал о работающем приборе — переход не к случаю."""
    guard = make_device_is_on()

    assert guard.deny_reason(None, {}) == "not_applicable"
    assert guard.deny_reason(None, {"_device_is_on": True}) is None


@pytest.mark.asyncio
async def test_transient_guard_does_not_fill_the_journal() -> None:
    """Обычное событие по такому переходу не даёт отказа условия.

    Переход, которому разового признака не хватает, движок пропускает молча; если
    он был единственным, событие называется «нет подходящего перехода» — оно
    пишется один раз на пару (BACKLOG B65) и не считается потоком.
    """
    engine = FSMEngine(event_bus=EventBus())
    published: list[tuple[str, dict[str, Any]]] = []

    async def collector(event_type: str, payload: dict[str, Any], trace_id: str = "") -> None:
        """Запомнить событие шины."""
        published.append((event_type, dict(payload)))

    assert engine.event_bus is not None
    engine.event_bus.subscribe("fsm.rejected", collector)
    engine.register_definition(
        FSMDefinition(
            entity_id="fan.base_smart_ventilation_modes_10",
            initial_state="AIRING",
            states=("AIRING", "IDLE"),
            transitions=(
                Transition(
                    from_state="AIRING",
                    to_state="IDLE",
                    trigger="settings_changed",
                    guard=make_device_is_off(),  # type: ignore[arg-type]
                ),
            ),
            target_device_id="fan.base_smart",
            params={},
        ),
        restore_state=False,
    )

    await engine.trigger("fan.base_smart_ventilation_modes_10", "settings_changed")
    await engine._drain_publish_tasks()  # noqa: SLF001 — дождаться публикации

    reasons = [payload.get("reason") for _event, payload in published]
    assert "guard_failed" not in reasons, f"разовый признак назван отказом условия: {reasons}"
    assert "not_applicable" not in reasons, "служебная причина утекла в журнал"
    counts = engine.rejection_counts()
    assert "guard_failed" not in counts, f"разовый признак попал в счётчик отказов: {counts}"


class TestRoleBranches:
    """Ветки режимов: не тот прибор — переход не относится (BACKLOG B74).

    Один шаблон обслуживает и рекуператор (приток), и вытяжку санузла. Ветки
    притока у вытяжки не к случаю — раньше они давали `guard_failed` на каждом
    показании датчика (около 290 записей в сутки).
    """

    def test_supply_branches_are_not_applicable_for_exhaust(self) -> None:
        """Ветки притока у вытяжки — не к этому прибору."""
        exhaust = {"ventilation_role": "exhaust", "ventilation_enabled": True}

        assert make_should_run_max_supply().deny_reason(None, exhaust) == "not_applicable"
        assert make_owner_wants_airing().deny_reason(None, exhaust) == "not_applicable"
        assert make_mode_for_weather().deny_reason(None, exhaust) == "not_applicable"

    def test_exhaust_branch_is_not_applicable_for_supply(self) -> None:
        """Ветка вытяжки у рекуператора — не к этому прибору."""
        supply = {"ventilation_role": "supply", "ventilation_enabled": True}

        assert make_should_run_exhaust().deny_reason(None, supply) == "not_applicable"

    def test_house_flag_still_named_on_own_branch(self) -> None:
        """На своей ветке отказ владельца по-прежнему назван своим именем."""
        supply = {"ventilation_role": "supply", "ventilation_enabled": False}

        reason = make_should_run_max_supply().deny_reason(None, supply)

        assert reason not in (None, "not_applicable"), f"причина не названа: {reason!r}"
