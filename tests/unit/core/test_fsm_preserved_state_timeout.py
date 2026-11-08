"""Срок пребывания в состоянии и само-переходы (B12, живая находка 2026-11-08).

Боевой случай: масляный радиатор гостевой спальни. Автомат вошёл в HEATING,
включил прибор и взвёл страховочный таймер на 15 минут. Каждые ~10 минут
приходило показание датчика, и срабатывал само-переход ``HEATING → HEATING``
(``may_keep_heating``, без действия). Каждый такой переход заново взводил
таймер — аварийное выключение не наступало никогда. В итоге собственный таймер
розетки (20 минут) выключил прибор первым, автомат остался в HEATING с
выключенным прибором и не мог снова включить обогрев.

Правило: ``timeout_sec`` — это «сколько можно находиться в состоянии». Поэтому
само-переход по умолчанию срок продлевает (так работают удержание света по
движению и повтор «Притока MAX» в вентиляции), но шаблон может явно запретить
продление: ``extends_timeout: false``. Тогда срок остаётся тем же, что был при
входе в состояние.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio

import pytest

from core.fsm.engine import FSMDefinition, FSMEngine, Transition


ENTITY_ID = "switch.probe_climate_control_10"


def _definition(extends_timeout: bool) -> FSMDefinition:
    """Определение с само-переходом и страховочным таймером.

    Args:
        extends_timeout: Продлевает ли само-переход срок пребывания.

    Returns:
        Описание автомата.
    """
    return FSMDefinition(
        entity_id=ENTITY_ID,
        initial_state="IDLE",
        states=("IDLE", "HEATING"),
        transitions=(
            Transition(from_state="IDLE", to_state="HEATING", trigger="start"),
            Transition(
                from_state="HEATING",
                to_state="HEATING",
                trigger="refresh",
                extends_timeout=extends_timeout,
            ),
            Transition(from_state="HEATING", to_state="IDLE", trigger="timeout", timeout_sec=1.0),
        ),
    )


async def test_self_transition_should_keep_deadline_when_extension_disabled() -> None:
    """Само-переход без продления не отодвигает страховочное выключение."""
    engine = FSMEngine()
    engine.register_definition(_definition(extends_timeout=False))

    await engine.trigger(ENTITY_ID, "start", trace_id="t1")
    first_timer = engine._timers[ENTITY_ID]  # noqa: SLF001
    entered_at = engine.get_state(ENTITY_ID).entered_at  # type: ignore[union-attr]

    await asyncio.sleep(0.5)
    assert await engine.trigger(ENTITY_ID, "refresh", trace_id="t2") is True

    assert engine._timers[ENTITY_ID] is first_timer, (  # noqa: SLF001
        "таймер перевзведён: срок состояния снова начался с само-перехода"
    )
    assert engine.get_state(ENTITY_ID).entered_at == entered_at, (  # type: ignore[union-attr]
        "время входа в состояние сдвинулось само-переходом"
    )

    await asyncio.sleep(0.7)
    assert engine.get_state(ENTITY_ID).current_state == "IDLE", (  # type: ignore[union-attr]
        "страховочный таймер не сработал через 1.0 с от входа в HEATING"
    )


async def test_self_transition_should_restart_deadline_by_default() -> None:
    """Само-переход по умолчанию продлевает срок — как у света и вентиляции."""
    engine = FSMEngine()
    engine.register_definition(_definition(extends_timeout=True))

    await engine.trigger(ENTITY_ID, "start", trace_id="t1")
    first_timer = engine._timers[ENTITY_ID]  # noqa: SLF001
    entered_at = engine.get_state(ENTITY_ID).entered_at  # type: ignore[union-attr]

    await asyncio.sleep(0.5)
    assert await engine.trigger(ENTITY_ID, "refresh", trace_id="t2") is True

    assert engine._timers[ENTITY_ID] is not first_timer, (  # noqa: SLF001
        "таймер не перезапустился на само-переходе по умолчанию"
    )
    assert first_timer.cancelled() or first_timer.done()
    assert engine.get_state(ENTITY_ID).entered_at > entered_at, (  # type: ignore[union-attr]
        "время входа не обновилось на продлевающем само-переходе"
    )

    await asyncio.sleep(0.7)
    assert engine.get_state(ENTITY_ID).current_state == "HEATING", (  # type: ignore[union-attr]
        "продлевающий само-переход не отодвинул выключение"
    )

    await asyncio.sleep(0.5)
    assert engine.get_state(ENTITY_ID).current_state == "IDLE"  # type: ignore[union-attr]


class _RecordingPersistence:
    """Хранилище, помнящее настенное время входа в состояние."""

    def __init__(self) -> None:
        """Создать пустое хранилище."""
        self.entered_at: list[float] = []

    def load_state(self, entity_id: str) -> None:
        """Состояния нет — каждый запуск чистый.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Всегда None.
        """
        del entity_id
        return None

    async def save_state_async(
        self, entity_id: str, state: str, context: dict, entered_at: float
    ) -> None:
        """Запомнить время входа.

        Args:
            entity_id: Идентификатор автомата.
            state: Состояние.
            context: Контекст.
            entered_at: Настенное время входа.

        Returns:
            Ничего.
        """
        del entity_id, state, context
        self.entered_at.append(entered_at)

    def save_state(self, entity_id: str, state: str, context: dict, entered_at: float) -> None:
        """Запомнить время входа синхронно.

        Args:
            entity_id: Идентификатор автомата.
            state: Состояние.
            context: Контекст.
            entered_at: Настенное время входа.

        Returns:
            Ничего.
        """
        del entity_id, state, context
        self.entered_at.append(entered_at)


async def test_preserved_self_transition_should_keep_persisted_entry_time() -> None:
    """Перезапуск не должен дарить состоянию новый срок после само-перехода."""
    persistence = _RecordingPersistence()
    engine = FSMEngine(persistence=persistence)  # type: ignore[arg-type]
    engine.register_definition(_definition(extends_timeout=False), restore_state=False)

    await engine.trigger(ENTITY_ID, "start", trace_id="t1")
    first_wall = persistence.entered_at[-1]

    await asyncio.sleep(0.1)
    await engine.trigger(ENTITY_ID, "refresh", trace_id="t2")
    second_wall = persistence.entered_at[-1]

    assert second_wall == pytest.approx(first_wall, abs=0.05), (
        "сохранённое время входа сдвинулось само-переходом: после перезапуска "
        "страховочный таймер начнёт отсчёт заново"
    )

    engine._timers.pop(ENTITY_ID, None)  # noqa: SLF001
