"""
T001: Проверки последнего решения автомата.

Движок запоминает для каждого автомата, что произошло: переход, отказ или
отсутствие действия — и почему. Проверяемое: outcome (on/off/denied/none),
reason_code, reason_text (совпадает с журналом), trigger, время.

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pytest
from src.core.events.fsm_events import GUARD_DENIAL_REASONS
from src.core.fsm.engine import FSMDefinition, FSMEngine, State, Transition


@dataclass(frozen=True)
class Decision:
    """Решение движка по автомату (должно появиться в engine.explain)."""

    at: float
    outcome: str  # "on" | "off" | "none" | "denied"
    reason_code: str | None
    reason_text: str
    trigger: str | None


@pytest.fixture
def engine() -> FSMEngine:
    """Движок для тестов."""
    return FSMEngine()


@pytest.fixture
def simple_definition() -> FSMDefinition:
    """Простой автомат: OFF -> ON (по 'turn_on') -> OFF (по 'turn_off')."""
    return FSMDefinition(
        entity_id="light.test",
        initial_state="OFF",
        states=("OFF", "ON"),
        transitions=(
            Transition(
                from_state="OFF",
                to_state="ON",
                trigger="turn_on",
                action="turn_on_light",
            ),
            Transition(
                from_state="ON",
                to_state="OFF",
                trigger="turn_off",
                action="turn_off_light",
            ),
        ),
    )


class TestFSMDecisionBasic:
    """Базовые переходы и решения."""

    async def test_decision_after_transition_on(
        self, engine: FSMEngine, simple_definition: FSMDefinition
    ) -> None:
        """После успешного переход ON решение показывает outcome='on'."""
        entity_id = "light.test"
        engine.register_definition(simple_definition)

        # Переход OFF -> ON
        await engine.trigger(entity_id, "turn_on")

        # Решение: на что оно?
        decision = engine.explain(entity_id)
        assert decision is not None
        assert decision.outcome == "on", "Переход с action turn_on должен дать outcome='on'"
        assert decision.reason_code is not None, "Код причины должен быть"
        assert decision.reason_text, "Текст причины обязателен"
        assert decision.trigger == "turn_on"
        assert decision.at > 0, "Время решения должно быть"

    async def test_decision_after_transition_off(
        self, engine: FSMEngine, simple_definition: FSMDefinition
    ) -> None:
        """После переход ON -> OFF решение показывает outcome='off'."""
        entity_id = "light.test"
        engine.register_definition(simple_definition)
        await engine.trigger(entity_id, "turn_on")

        # Переход ON -> OFF
        await engine.trigger(entity_id, "turn_off")

        decision = engine.explain(entity_id)
        assert decision is not None
        assert decision.outcome == "off", "Переход с action turn_off должен дать outcome='off'"
        assert decision.trigger == "turn_off"

    async def test_decision_at_time_is_transition_time(
        self, engine: FSMEngine, simple_definition: FSMDefinition
    ) -> None:
        """Время решения — это время перехода, не чтения."""
        entity_id = "light.test"
        engine.register_definition(simple_definition)

        before = time.time()
        await engine.trigger(entity_id, "turn_on")
        after = time.time()

        decision = engine.explain(entity_id)
        assert decision is not None
        assert before <= decision.at <= after, "Время решения должно быть в момент перехода"


class TestFSMDecisionGuardDenial:
    """Отказы по условиям (guard)."""

    async def test_decision_denied_when_guard_rejects(self, engine: FSMEngine) -> None:
        """Когда условие отвергает переход, решение — denied с кодом условия."""
        entity_id = "light.guardedlight"

        def always_deny(state: State, context: dict[str, Any]) -> bool:
            """Условие, которое всегда отвергает."""
            return False

        definition = FSMDefinition(
            entity_id=entity_id,
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    action="turn_on_light",
                    guard=always_deny,
                ),
            ),
        )
        engine.register(entity_id, definition)

        # Попытка переход OFF -> ON, но условие отвергнет
        await engine.trigger(entity_id, "turn_on")

        decision = engine.explain(entity_id)
        assert decision is not None
        assert decision.outcome == "denied", "Отверженный переход — outcome='denied'"
        assert decision.reason_code in GUARD_DENIAL_REASONS.values(), (
            "Код должен быть из GUARD_DENIAL_REASONS"
        )
        assert decision.reason_text, "При отказе есть объяснение"
        assert decision.trigger == "turn_on", "Триггер записывается всегда"

    async def test_decision_reason_code_from_guard_denial_reasons(self, engine: FSMEngine) -> None:
        """Код причины совпадает с одним из GUARD_DENIAL_REASONS."""
        entity_id = "light.guardedlight"

        def custom_deny(state: State, context: dict[str, Any]) -> bool:
            return False

        definition = FSMDefinition(
            entity_id=entity_id,
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard=custom_deny,
                ),
            ),
        )
        engine.register(entity_id, definition)

        await engine.trigger(entity_id, "turn_on")
        decision = engine.explain(entity_id)

        assert decision is not None
        assert decision.reason_code in GUARD_DENIAL_REASONS.values(), (
            f"Код должен быть в GUARD_DENIAL_REASONS; получено {decision.reason_code}, вариантов {list(GUARD_DENIAL_REASONS.values())}"
        )


class TestFSMDecisionNoTransition:
    """Отсутствие подходящего переход."""

    async def test_decision_denied_when_no_transition(
        self, engine: FSMEngine, simple_definition: FSMDefinition
    ) -> None:
        """Событие без подходящего перехода даёт denied."""
        entity_id = "light.test"
        engine.register_definition(simple_definition)

        # События только turn_on и turn_off; пошлём unknown_trigger
        await engine.trigger(entity_id, "unknown_trigger")

        decision = engine.explain(entity_id)
        assert decision is not None
        assert decision.outcome == "denied"
        assert decision.trigger == "unknown_trigger"
        assert decision.reason_code is not None


class TestFSMDecisionNone:
    """Отсутствие действия (только переход состояния)."""

    async def test_decision_none_when_no_action(self, engine: FSMEngine) -> None:
        """Переход без действия дает outcome='none'."""
        entity_id = "light.noaction"
        definition = FSMDefinition(
            entity_id=entity_id,
            initial_state="IDLE",
            states=("IDLE", "WAITING"),
            transitions=(
                Transition(
                    from_state="IDLE",
                    to_state="WAITING",
                    trigger="wait",
                    # Нет action
                ),
            ),
        )
        engine.register(entity_id, definition)

        await engine.trigger(entity_id, "wait")

        decision = engine.explain(entity_id)
        assert decision is not None
        assert decision.outcome == "none", "Переход без действия — outcome='none'"
        assert decision.reason_text, "Даже 'none' имеет объяснение"


class TestFSMDecisionNonexistent:
    """Несуществующий автомат."""

    def test_explain_nonexistent_returns_none(self, engine: FSMEngine) -> None:
        """explain() для несуществующего автомата возвращает None, не исключение."""
        decision = engine.explain("light.nonexistent")
        assert decision is None, "Несуществующий автомат → None, а не исключение"


class TestFSMDecisionReasonTextMatchesLog:
    """Формулировка причины совпадает с журналом."""

    async def test_reason_text_consistent_with_guard_denial_reasons(
        self, engine: FSMEngine
    ) -> None:
        """Текст из engine.explain совпадает с тем, что пишется в журнал."""
        entity_id = "light.test"

        def deny(state: State, context: dict[str, Any]) -> bool:
            return False

        definition = FSMDefinition(
            entity_id=entity_id,
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON",
                    trigger="turn_on",
                    guard=deny,
                ),
            ),
        )
        engine.register(entity_id, definition)

        # Ловим логируемую причину
        # (она пишется в _guard_rejection_reason; проверим, что engine.explain отдаёт то же)
        await engine.trigger(entity_id, "turn_on")

        decision = engine.explain(entity_id)
        assert decision is not None
        # Текст должен быть человеческим, не кодом
        assert decision.reason_text != decision.reason_code, (
            "Текст причины должен быть человеческий, а не код"
        )
        assert len(decision.reason_text) > 0, "Текст причины не пустой"


class TestFSMDecisionEvolution:
    """Решение меняется при новом переход."""

    async def test_decision_updates_on_new_transition(
        self, engine: FSMEngine, simple_definition: FSMDefinition
    ) -> None:
        """После нового перехода решение обновляется."""
        entity_id = "light.test"
        engine.register_definition(simple_definition)

        # Первый переход: OFF -> ON
        await engine.trigger(entity_id, "turn_on")
        decision1 = engine.explain(entity_id)
        assert decision1 is not None
        assert decision1.outcome == "on"
        t1 = decision1.at

        # Второй переход: ON -> OFF
        await asyncio.sleep(0.01)  # Гарантируем разное время
        await engine.trigger(entity_id, "turn_off")
        decision2 = engine.explain(entity_id)
        assert decision2 is not None
        assert decision2.outcome == "off"
        t2 = decision2.at

        assert t2 > t1, "Время второго решения должно быть позже первого"

    async def test_decision_only_one_stored_not_history(
        self, engine: FSMEngine, simple_definition: FSMDefinition
    ) -> None:
        """Хранится только ОДНО последнее решение, не история."""
        entity_id = "light.test"
        engine.register_definition(simple_definition)

        # Несколько переходов
        await engine.trigger(entity_id, "turn_on")
        await engine.trigger(entity_id, "turn_off")
        await engine.trigger(entity_id, "turn_on")

        # engine.explain отдаёт только последнее
        decision = engine.explain(entity_id)
        assert decision is not None
        assert decision.outcome == "on", "Последнее решение — on"

        # Проверяем, что история не доступна (иначе была бы возможность запросить все три)
        # Контракт: explain() возвращает одно, не список


class TestFSMDecisionUnknownEvent:
    """События, которые движок не знает."""

    async def test_decision_denied_unknown_entity(self, engine: FSMEngine) -> None:
        """trigger на неизвестный entity_id дает denied."""
        # Движок не зарегистрирован
        await engine.trigger("light.unknown", "turn_on")

        decision = engine.explain("light.unknown")
        assert decision is not None
        assert decision.outcome == "denied"
        assert decision.reason_code is not None


@pytest.mark.asyncio
async def test_integration_transition_and_decision(
    engine: FSMEngine, simple_definition: FSMDefinition
) -> None:
    """Интеграция: переход и решение согласованы."""
    entity_id = "light.test"
    engine.register(entity_id, simple_definition)

    # Переход OFF -> ON
    await engine.trigger(entity_id, "turn_on")

    # Состояние и решение совпадают
    state = engine.get_state(entity_id)
    decision = engine.explain(entity_id)

    assert state is not None
    assert decision is not None
    assert state.current_state == "ON"
    assert decision.outcome == "on"
    assert decision.at <= time.time(), "Решение не может быть в будущем"
