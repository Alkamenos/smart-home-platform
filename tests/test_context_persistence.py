"""
Тест сохранения контекста через несколько переходов.

Проверяет, что данные в state.context не теряются при переходах между состояниями.
"""

import pytest
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


def add_counter(state: State, context: dict) -> dict:
    """Увеличивает счетчик в контексте."""
    current = state.context.get("counter", 0)
    return {"counter": current + 1}


def add_timestamp(state: State, context: dict) -> dict:
    """Добавляет timestamp в контекст."""
    return {"last_action": datetime.now().timestamp()}


def preserve_context(state: State, context: dict) -> dict:
    """Action, который ничего не добавляет (проверяет сохранение существующего контекста)."""
    return {}


@pytest.mark.asyncio
async def test_context_persists_across_transitions():
    """
    Сценарий: Несколько переходов, каждый добавляет данные в контекст.
    Ожидание: Все данные сохраняются.
    """
    engine = FSMEngine()
    entity_id = "counter.device"

    engine.register_action("add_counter", add_counter)
    engine.register_action("add_timestamp", add_timestamp)
    engine.register_action("preserve_context", preserve_context)

    definition = FSMDefinition(
        entity_id=entity_id,
        initial_state="state_a",
        states=("state_a", "state_b", "state_c"),
        debounce_sec=0.0,
        transitions=(
            Transition(from_state="state_a", trigger="next", to_state="state_b", action="add_counter"),
            Transition(from_state="state_b", trigger="next", to_state="state_c", action="add_timestamp"),
            Transition(from_state="state_c", trigger="next", to_state="state_a", action="preserve_context"),
        )
    )
    engine.register_definition(definition)

    # Переход 1: state_a -> state_b (добавляет counter=1)
    with freeze_time("2026-09-09 12:00:00"):
        await engine.trigger(entity_id, "next", trace_id="ctx-001")
        state = engine.get_state(entity_id)
        assert state.context.get("counter") == 1
        assert "last_action" not in state.context

    # Переход 2: state_b -> state_c (добавляет last_action, counter должен остаться)
    with freeze_time("2026-09-09 12:00:01"):
        await engine.trigger(entity_id, "next", trace_id="ctx-002")
        state = engine.get_state(entity_id)
        assert state.context.get("counter") == 1, "Counter должен сохраниться"
        assert state.context.get("last_action") == datetime(2026, 9, 9, 12, 0, 1).timestamp()

    # Переход 3: state_c -> state_a (ничего не добавляет, оба значения должны остаться)
    with freeze_time("2026-09-09 12:00:02"):
        await engine.trigger(entity_id, "next", trace_id="ctx-003")
        state = engine.get_state(entity_id)
        assert state.context.get("counter") == 1, "Counter должен сохраниться"
        assert state.context.get("last_action") == datetime(2026, 9, 9, 12, 0,
                                                            1).timestamp(), "last_action должен сохраниться"


@pytest.mark.asyncio
async def test_context_accumulation():
    """
    Проверяет, что счетчик корректно увеличивается через несколько переходов.
    """
    engine = FSMEngine()
    entity_id = "accumulator.device"

    engine.register_action("add_counter", add_counter)

    definition = FSMDefinition(
        entity_id=entity_id,
        initial_state="off",
        states=("off", "on"),
        debounce_sec=0.0,
        transitions=(
            Transition(from_state="off", trigger="toggle", to_state="on", action="add_counter"),
            Transition(from_state="on", trigger="toggle", to_state="off", action="add_counter"),
        )
    )
    engine.register_definition(definition)

    # 5 переключений
    for i in range(5):
        await engine.trigger(entity_id, "toggle", trace_id=f"acc-{i:03d}")

    state = engine.get_state(entity_id)
    assert state.context.get("counter") == 5, "Счетчик должен быть равен 5"
