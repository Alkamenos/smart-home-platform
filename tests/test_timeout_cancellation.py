"""
Детальный тест отмены таймеров.

Проверяет, что при каждом переходе старые таймеры отменяются,
и только один таймер активен в любой момент времени.
"""

import pytest
import asyncio
from datetime import datetime
from freezegun import freeze_time
from unittest.mock import patch
import time

from src.smart_home.core.fsm import FSMEngine, State, FSMDefinition, Transition


@pytest.fixture(autouse=True)
def freeze_asyncio_time():
    import asyncio
    real_get_event_loop = asyncio.get_event_loop

    with patch("src.smart_home.core.fsm.asyncio.get_event_loop") as mock_get_loop:
        def side_effect():
            loop = real_get_event_loop()
            loop.time = time.time
            return loop

        mock_get_loop.side_effect = side_effect
        yield


def action_noop(state: State, context: dict) -> dict:
    return {}


@pytest.mark.asyncio
async def test_timer_cancellation_on_rapid_transitions():
    """
    Сценарий: Быстрые переходы между состояниями.
    Ожидание: Только последний таймер остается активным.
    """
    engine = FSMEngine()
    entity_id = "light.test"

    definition = FSMDefinition(
        entity_id=entity_id,
        initial_state="off",
        states=("off", "on", "dimmed"),
        debounce_sec=0.0,
        transitions=(
            Transition(from_state="off", trigger="turn_on", to_state="on", action=action_noop, timeout_sec=10.0),
            Transition(from_state="on", trigger="dim", to_state="dimmed", action=action_noop, timeout_sec=20.0),
            Transition(from_state="dimmed", trigger="brighten", to_state="on", action=action_noop, timeout_sec=15.0),
        )
    )
    engine.register_definition(definition)

    # Переход 1: off -> on (таймер 10 сек)
    with freeze_time("2026-09-09 12:00:00"):
        await engine.trigger(entity_id, "turn_on", trace_id="timer-001")
        assert len(engine._timers) == 1, "Должен быть 1 таймер"
        timer_task_1 = engine._timers[entity_id]

    # Переход 2: on -> dimmed (таймер 20 сек, старый должен отмениться)
    with freeze_time("2026-09-09 12:00:01"):
        await engine.trigger(entity_id, "dim", trace_id="timer-002")
        assert len(engine._timers) == 1, "Должен быть 1 таймер (старый отменен)"
        timer_task_2 = engine._timers[entity_id]

        # Проверяем, что это ДРУГОЙ таймер
        assert timer_task_1 is not timer_task_2, "Должен быть новый таймер"

        # Проверяем, что старый таймер отменен
        assert timer_task_1.cancelled() or timer_task_1.done(), "Старый таймер должен быть отменен"

    # Переход 3: dimmed -> on (таймер 15 сек, предыдущий должен отмениться)
    with freeze_time("2026-09-09 12:00:02"):
        await engine.trigger(entity_id, "brighten", trace_id="timer-003")
        assert len(engine._timers) == 1, "Должен быть 1 таймер"
        timer_task_3 = engine._timers[entity_id]

        assert timer_task_2.cancelled() or timer_task_2.done(), "Предыдущий таймер должен быть отменен"
        assert timer_task_3 is not timer_task_2, "Должен быть новый таймер"


@pytest.mark.asyncio
async def test_no_timer_without_timeout():
    """
    Проверяет, что переходы без timeout_sec не создают таймеров.
    """
    engine = FSMEngine()
    entity_id = "light.no_timeout"

    definition = FSMDefinition(
        entity_id=entity_id,
        initial_state="off",
        states=("off", "on"),
        debounce_sec=0.0,
        transitions=(
            Transition(from_state="off", trigger="turn_on", to_state="on", action=action_noop),
            # Нет timeout_sec!
        )
    )
    engine.register_definition(definition)

    with freeze_time("2026-09-09 12:00:00"):
        await engine.trigger(entity_id, "turn_on", trace_id="no-timer-001")
        assert len(engine._timers) == 0, "Не должно быть таймеров без timeout_sec"
