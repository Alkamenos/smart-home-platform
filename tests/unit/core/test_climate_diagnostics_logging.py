"""Климат и вентиляция пишут подробный след для утреннего разбора (спека 014).

Правило владельца (`.ai/04_RULES.md`): утром по журналу должно быть восстановимо,
что пришло, что решили и почему, без обращения к коду. Свет остаётся при прежнем
bounded-поведении, а климат и вентиляция пишут **каждое** решение:

- отказ перехода — видимой строкой с причиной и входом (даже если отказ повторный);
- разрешённый переход — видимой строкой с действием и входом.

Проверка ловит loguru сокетом: движок пишет через loguru, и `caplog` его не видит
(урок #70).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from loguru import logger

from core.fsm.engine import FSMDefinition, FSMEngine, Transition


VENTILATION = "fan.base_smart_ventilation_modes_10"
LIGHT = "light.kitchen_lighting_10"


def _deny(state: Any, context: dict[str, Any]) -> bool:
    """Условие, которое всегда отказывает.

    Args:
        state: Состояние автомата.
        context: Контекст перехода.

    Returns:
        Всегда False.
    """
    del state, context
    return False


_deny.deny_reason = lambda state, context: "turned_off_by_owner"  # type: ignore[attr-defined]


def _allow(state: Any, context: dict[str, Any]) -> bool:
    """Условие, которое всегда разрешает.

    Args:
        state: Состояние автомата.
        context: Контекст перехода.

    Returns:
        Всегда True.
    """
    del state, context
    return True


def _definition(entity_id: str, guard: Any) -> FSMDefinition:
    """Автомат климата/вентиляции с одним переходом.

    Args:
        entity_id: Идентификатор автомата.
        guard: Условие перехода.

    Returns:
        Определение автомата.
    """
    return FSMDefinition(
        entity_id=entity_id,
        initial_state="IDLE",
        states=["IDLE", "SUPPLY"],
        transitions=[
            Transition(
                from_state="IDLE",
                to_state="SUPPLY",
                trigger="temperature_changed",
                guard=guard,
                action=lambda *a, **k: None,
            )
        ],
    )


@pytest.fixture
def captured() -> Iterator[list[str]]:
    """Захватывать сообщения loguru на время проверки.

    Yields:
        Список сообщений, пополняемый по ходу выполнения.
    """
    messages: list[str] = []

    def _sink(message: Any) -> None:
        messages.append(str(message))

    handler_id = logger.add(_sink, level="WARNING")
    try:
        yield messages
    finally:
        logger.remove(handler_id)


@pytest.mark.asyncio
async def test_ventilation_denial_is_logged_with_reason_and_input(captured: list[str]) -> None:
    """Отказ вентиляции пишется с причиной и входом.

    Args:
        captured: Захваченные сообщения.

    Returns:
        Ничего.
    """
    engine = FSMEngine()
    engine.register_definition(_definition(VENTILATION, _deny))

    await engine.trigger(
        VENTILATION,
        "temperature_changed",
        external_ctx={"outside_temperature": 11.0, "temperature": 19.0, "ventilation_on": False},
    )

    denials = [m for m in captured if "ДИАГНОСТИКА" in m and "ОТКАЗ" in m]
    assert denials, f"отказ вентиляции не попал в журнал: {captured}"
    line = denials[0]
    assert "turned_off_by_owner" in line, f"причина отказа не названа: {line}"
    assert "outside_temperature" in line and "temperature" in line, (
        f"во входе нет показаний датчиков: {line} — утром не понять, почему отказали"
    )


@pytest.mark.asyncio
async def test_ventilation_denial_is_not_bounded(captured: list[str]) -> None:
    """Повторный отказ вентиляции тоже виден (в отличие от света).

    Args:
        captured: Захваченные сообщения.

    Returns:
        Ничего.
    """
    engine = FSMEngine()
    engine.register_definition(_definition(VENTILATION, _deny))

    for _ in range(3):
        await engine.trigger(VENTILATION, "temperature_changed", external_ctx={})

    denials = [m for m in captured if "решение отказано" in m]
    assert len(denials) == 3, (
        f"отказов вентиляции в журнале {len(denials)} из 3: разбор за сутки по "
        "одной записи невозможен"
    )


@pytest.mark.asyncio
async def test_light_denial_stays_bounded(captured: list[str]) -> None:
    """Отказ света остаётся ограниченным: подробность только для климата.

    Args:
        captured: Захваченные сообщения.

    Returns:
        Ничего.
    """
    engine = FSMEngine()
    engine.register_definition(_definition(LIGHT, _deny))

    for _ in range(3):
        await engine.trigger(LIGHT, "temperature_changed", external_ctx={})

    mentions = [m for m in captured if "light.kitchen_lighting_10" in m]
    assert len(mentions) == 1, (
        f"свет записан {len(mentions)} раз из 3: подробность для климата не "
        "должна раскармливать журнал событиями света"
    )


@pytest.mark.asyncio
async def test_ventilation_allow_is_logged(captured: list[str]) -> None:
    """Разрешённое решение вентиляции пишется с действием и входом.

    Args:
        captured: Захваченные сообщения.

    Returns:
        Ничего.
    """
    engine = FSMEngine()
    engine.register_definition(_definition(VENTILATION, _allow))

    await engine.trigger(
        VENTILATION, "temperature_changed", external_ctx={"outside_temperature": 11.0}
    )

    allowed = [m for m in captured if "ДИАГНОСТИКА" in m and "РАЗРЕШЕНО" in m]
    assert allowed, f"разрешённое решение вентиляции не записано: {captured}"
    assert "outside_temperature" in allowed[0]
