"""Восстановленное состояние должно восстановить и таймер.

Таймаут-переходы не переживали перезапуск (`src/features/lighting.yaml`:
`ON_MOTION --[timeout 30s]--> OFF`). Таймер жил только в памяти процесса, поэтому
после пересоздания контейнера автомат оставался в состоянии, из которого должен
был уйти по таймауту, и ждал триггера, который уже не придёт.

Доказательство из боевой базы: `light.svet_nad_stolom_lighting_10` = `ON_MOTION`
сохранён в 13:16, последний переход — тот же, за четыре часа ни одного. Сторож
честно сообщал `stuck: true`, `expected_timeout_sec: 30.0`. В доме свет
включался по движению и не гаснул никогда.

Что именно сломано
------------------

`FSMEngine.register_definition` восстанавливает `current_state` из
`state.json`, но:

- не ставит `entered_at` из сохранённых данных — подставляет `loop_time()`,
  то есть «сейчас», независимо от того, сколько автомат уже пролежал;
- не взводит таймер для восстановленного состояния.

Таймер взводится только в пути перехода (`engine.py:759`), а восстановление идёт
мимо него.

Ожидаемое поведение
-------------------

Таймер восстанавливается с **оставшимся** временем, а не с полным: состояние
пролежало 25 секунд из 30 — до перехода осталось 5, а не 30. Иначе перезапуск
таймер бы продлевал, и свет горел бы дольше объявленного, а с каждым
перезапуском всё сильнее.

Отдельно проверяется, что восстановление не проходит молча: без таймера
дефект не виден ни в логах, ни в `/ready` — только в доме.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from core.fsm.engine import FSMDefinition, FSMEngine, Transition


#: Состояния автомата освещения из `src/features/lighting.yaml`.
STATES = ("OFF", "ON_MOTION", "ON_MANUAL")

#: Ожидание в состоянии `ON_MOTION` — как объявлено в шаблоне.
MOTION_TIMEOUT_SEC = 30.0


def _lighting_definition() -> FSMDefinition:
    """Собрать определение автомата освещения из шаблона.

    Returns:
        Определение с тем же набором переходов, что и в `lighting.yaml`.
    """
    return FSMDefinition(
        entity_id="light.kitchen_lighting_10",
        initial_state="OFF",
        states=list(STATES),
        transitions=[
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                action=lambda *a, **k: None,
            ),
            Transition(
                from_state="ON_MOTION",
                to_state="OFF",
                trigger="timeout",
                action=lambda *a, **k: None,
                timeout_sec=MOTION_TIMEOUT_SEC,
            ),
        ],
    )


class _InMemoryPersistence:
    """Хранилище состояний в памяти — формат как у `state.json`."""

    def __init__(self, saved: dict[str, dict[str, Any]] | None = None) -> None:
        """Создать хранилище с готовым содержимым.

        Args:
            saved: Содержимое по идентификатору автомата.
        """
        self.saved: dict[str, dict[str, Any]] = saved or {}
        self.saved_calls: list[tuple[str, str]] = []

    def load_state(self, entity_id: str) -> tuple[str, dict[str, Any]] | None:
        """Прочитать сохранённое состояние.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Пара (состояние, контекст) либо None.
        """
        entry = self.saved.get(entity_id)
        if entry is None:
            return None
        return (entry["state"], entry.get("context", {}))

    async def save_state_async(self, entity_id: str, state: str, context: dict[str, Any]) -> None:
        """Записать состояние.

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.
            context: Контекст состояния.

        Returns:
            Ничего.
        """
        self.saved_calls.append((entity_id, state))
        self.saved[entity_id] = {"state": state, "context": context}

    def save_state(self, entity_id: str, state: str, context: dict[str, Any]) -> None:
        """Записать состояние синхронно.

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.
            context: Контекст состояния.

        Returns:
            Ничего.
        """
        self.saved[entity_id] = {"state": state, "context": context}


class _ManualClockPersistence(_InMemoryPersistence):
    """Хранилище, отдающее время входа в состояние по часам, которые двигает тест.

    Формат записи — как у настоящего `state.json`: `state`, `context` и
    `entered_at` настенным временем. Заглушка повторяет контракт, а не
    подстраивается под движок: иначе проверка проходила бы тем, что движок
    ожидает от неё, а не тем, что он действительно читает с диска.
    """

    def __init__(self, entered_at: float) -> None:
        """Создать хранилище с указанным временем входа.

        Args:
            entered_at: Настенное время входа в состояние.
        """
        super().__init__(
            saved={
                "light.kitchen_lighting_10": {
                    "state": "ON_MOTION",
                    "context": {},
                    "entered_at": entered_at,
                }
            }
        )

    def load_state_entry(self, entity_id: str) -> dict[str, Any] | None:
        """Прочитать запись автомата целиком.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Запись состояния либо None.
        """
        return self.saved.get(entity_id)


@pytest.mark.asyncio
class TestTimeoutSurvivesRestart:
    """Таймер переживает перезапуск."""

    async def test_restored_state_gets_a_timer(self) -> None:
        """Восстановленное состояние получает таймер.

        Returns:
            Ничего.
        """
        engine = FSMEngine()
        definition = _lighting_definition()
        engine.register_definition(definition)

        await engine.trigger(definition.entity_id, "motion_detected")

        state = engine.get_state(definition.entity_id)
        assert state is not None
        assert state.current_state == "ON_MOTION"
        assert engine._timers.get(definition.entity_id) is not None, (  # noqa: SLF001
            "переход по движению обязан взвести таймер — иначе нечего было бы "
            "восстанавливать. Проверка нужна как опора: без неё падение "
            "остальных означало бы «таймауты не работают вовсе», а не "
            "«не восстанавливаются»"
        )

    async def test_restart_restores_state_and_timer(self) -> None:
        """После перезапуска состояние `ON_MOTION` снова получает таймер.

        Returns:
            Ничего.
        """
        now = time.time()
        persistence = _ManualClockPersistence(entered_at=now - 5)

        engine = FSMEngine(persistence=persistence)  # type: ignore[arg-type]
        engine.register_definition(_lighting_definition())

        state = engine.get_state("light.kitchen_lighting_10")
        assert state is not None
        assert state.current_state == "ON_MOTION", (
            "состояние должно восстановиться — это и работало"
        )
        assert engine._timers.get("light.kitchen_lighting_10") is not None, (  # noqa: SLF001
            "состояние восстановилось, а таймер нет: автомат остаётся в "
            "`ON_MOTION` навсегда и ждёт триггера, который не придёт. Именно "
            "это наблюдалось в доме: свет горел с 13:16 до перезапуска "
            "контейнера (Known Issue #78)"
        )

    @pytest.mark.slow
    async def test_restored_timer_uses_remaining_time(self) -> None:
        """Восстановленный таймер считает остаток, а не полный срок.

        Returns:
            Ничего.
        """
        now = time.time()
        persistence = _ManualClockPersistence(entered_at=now - 25)

        engine = FSMEngine(persistence=persistence)  # type: ignore[arg-type]
        engine.register_definition(_lighting_definition())

        # 30 - 25 = 5 секунд до перехода. Даём чуть больше, чтобы отсеять
        # вариант «таймер взведён на полные 30 с».
        await asyncio.sleep(6.0)

        state = engine.get_state("light.kitchen_lighting_10")
        assert state is not None
        assert state.current_state == "OFF", (
            f"через 6 с после восстановления автомат всё ещё в "
            f"`{state.current_state}`, хотя из состояния, пролежавшего 25 с "
            f"из 30, переход по таймауту должен был произойти за 5 с. Таймер "
            f"взведён заново на полный срок, то есть перезапуск продлевает "
            f"горение, а с каждым перезапуском всё сильнее"
        )

    async def test_expired_timeout_fires_immediately(self) -> None:
        """Просроченный таймаут срабатывает сразу, а не через полный срок.

        Returns:
            Ничего.
        """
        now = time.time()
        # Автомат пролежал в состоянии дольше объявленного ожидания.
        persistence = _ManualClockPersistence(entered_at=now - 120)

        engine = FSMEngine(persistence=persistence)  # type: ignore[arg-type]
        engine.register_definition(_lighting_definition())

        await asyncio.sleep(0.5)

        state = engine.get_state("light.kitchen_lighting_10")
        assert state is not None
        assert state.current_state == "OFF", (
            f"состояние пролежало 120 с при ожидании 30 с, но после "
            f"перезапуска осталось в `{state.current_state}`. Отложенный "
            f"переход должен был произойти сразу: иначе восстановление "
            f"продлевает свечение на весь следующий цикл"
        )


def _state(entity_id: str, state: str) -> Any:
    """Собрать состояние вне цикла событий.

    Args:
        entity_id: Идентификатор автомата.
        state: Имя состояния.

    Returns:
        Состояние автомата.
    """
    from core.fsm.engine import State

    return State(current_state=state, entered_at=0.0, context={})
