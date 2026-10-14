"""Ночное условие и перезапуск таймера оверрайда (спека 017, B57/B59).

Два свойства, на которых стоит «возврат к автоматике через 60 минут от более
позднего события»:

1. ``is_night_time`` — отрицание ``is_day_time`` с тем же диапазоном дня: по нему
   декоративный свет возвращается в «горит», если ещё ночь.
2. Само-переход в ручном состоянии **перезапускает** таймер: именно так срок
   оверрайда считается от более позднего события (ручное действие или «мы спим»).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from core.fsm.engine import FSMDefinition, FSMEngine, Transition
from core.guards.builtin import make_is_day_time, make_is_night_time


def _at(hour: int, minute: int = 0) -> datetime:
    """Момент времени для подменённых часов.

    Args:
        hour: Час.
        minute: Минуты.

    Returns:
        Дата и время.
    """
    return datetime(2026, 10, 14, hour, minute)


def test_is_night_time_is_opposite_of_day() -> None:
    """Ночь и день не пересекаются и вместе покрывают сутки."""
    day = make_is_day_time("07:00-23:00", now=lambda: _at(12))
    night = make_is_night_time("07:00-23:00", now=lambda: _at(12))

    assert day(None, {}) is True
    assert night(None, {}) is False

    night_at_night = make_is_night_time("07:00-23:00", now=lambda: _at(2))
    assert night_at_night(None, {}) is True


@pytest.mark.asyncio
def test_manual_off_ends_the_hold_in_every_lit_state() -> None:
    """Ручное выключение принимается и из ON_MOTION, и из ON_HOLD (2026-10-14).

    Боевой случай: владелец погасил фонари, пока шло удержание по движению
    (ON_MOTION), а перехода «ручное выключение из ON_MOTION» в шаблоне не было —
    событие человека отвергалось как «нет такого перехода», и автомат продолжал
    считать свет горящим.
    """
    import yaml

    template = yaml.safe_load(Path("src/features/lighting.yaml").read_text(encoding="utf-8"))
    pairs = {
        (transition["from_state"], transition["trigger"]): transition.get("to_state")
        for transition in template["transitions"]
    }

    assert pairs.get(("ON_MOTION", "manual_switch_off")) == "OFF"
    assert pairs.get(("ON_HOLD", "manual_switch_off")) == "OFF"
    assert pairs.get(("ON_MANUAL", "manual_switch_off")) == "OFF"


@pytest.mark.asyncio
async def test_self_transition_should_restart_timeout() -> None:
    """Само-переход в состоянии перезапускает таймер (срок от более позднего)."""
    definition = FSMDefinition(
        entity_id="light.probe_lighting_10",
        initial_state="ON_MANUAL",
        states=["ON_MANUAL", "OFF"],
        transitions=[
            Transition(
                from_state="ON_MANUAL", to_state="OFF", trigger="timeout", timeout_sec=3600.0
            ),
            Transition(from_state="ON_MANUAL", to_state="ON_MANUAL", trigger="sleep_started"),
        ],
    )
    engine = FSMEngine()
    engine.register_definition(definition, restore_state=False)

    await engine.trigger("light.probe_lighting_10", "sleep_started")
    first = engine._timers["light.probe_lighting_10"]

    await engine.trigger("light.probe_lighting_10", "sleep_started")
    second = engine._timers["light.probe_lighting_10"]

    assert first is not second, "таймер не перезапустился на само-переходе"
    assert first.cancelled() or first.done(), "прежний таймер не снят"
    assert engine.get_state("light.probe_lighting_10").current_state == "ON_MANUAL"

    await asyncio.sleep(0)
    engine._timers.pop("light.probe_lighting_10", None)
    second.cancel()
