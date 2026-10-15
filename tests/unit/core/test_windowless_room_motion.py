"""Комнаты без окон: свет по движению работает и после ручного выключения.

Требование владельца 2026-10-15 (боевой разбор): утром погасили свет в санузле
руками — и комната замолчала на час, потому что ручное действие включает
блокировку оверрайда на 60 минут, а движение её не отменяет. В комнатах без окон
(`always_on_motion_rooms`: санузел, контейнер) так нельзя: днём там так же темно,
другого света нет, и следующий вошедший должен получить свет.

Поэтому включение по движению в этих комнатах помечается как правило
безопасности (`bypass_lockout`) — тем же признаком, которым пользуется ночное
гашение света. Блокировка при этом остаётся: она по-прежнему защищает решение
автоматики (таймауты, расписание), обходится только включение по движению.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.commands.dispatcher import CommandIntent
from core.fsm.engine import FSMDefinition, FSMEngine, Transition


FSM_ID = "light.vykliuchatel_sanuzel_switch1_lighting_10"
ROOM = "sanuzel"


class _RecordingDispatcher:
    """Диспетчер-двойник: помнит интенты и их признак обхода блокировки."""

    def __init__(self) -> None:
        """Собрать пустой список."""
        self.intents: list[CommandIntent] = []

    async def submit(self, intent: CommandIntent) -> bool:
        """Запомнить интент.

        Args:
            intent: Намерение команды.

        Returns:
            True — команда принята.
        """
        self.intents.append(intent)
        return True


def _turn_on(state: Any, context: dict[str, Any]) -> CommandIntent:
    """Действие включения света: несёт признак обхода блокировки.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст перехода.

    Returns:
        Намерение команды.
    """
    del state
    return CommandIntent(
        device_id=str(context.get("target_device_id") or ""),
        domain="light",
        service="turn_on",
        data={},
        priority=50,
        source=str(context.get("source") or "lighting"),
        bypass_lockout=bool(context.get("bypass_lockout", False)),
    )


def _engine(*, room: str, windowless: list[str]) -> tuple[FSMEngine, _RecordingDispatcher]:
    """Собрать движок с одним автоматом света.

    Args:
        room: Комната автомата.
        windowless: Комнаты без окон (`always_on_motion_rooms`).

    Returns:
        Движок и помнящий команды диспетчер.
    """
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    engine.register_definition(
        FSMDefinition(
            entity_id=FSM_ID,
            initial_state="OFF",
            states=("OFF", "ON_MOTION"),
            transitions=(
                Transition(
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger="motion_detected",
                    action=_turn_on,  # type: ignore[arg-type]
                ),
            ),
            target_device_id="light.vykliuchatel_sanuzel_switch1",
            room=room,
            params={"always_on_motion_rooms": windowless},
        ),
        restore_state=False,
    )
    return engine, dispatcher


@pytest.mark.asyncio
async def test_windowless_room_motion_bypasses_lockout() -> None:
    """Санузел: включение по движению обходит ручную блокировку."""
    engine, dispatcher = _engine(room=ROOM, windowless=[ROOM])

    await engine.trigger(FSM_ID, "motion_detected")

    assert dispatcher.intents, "команда не отправлена"
    assert dispatcher.intents[0].bypass_lockout is True, (
        "движение в комнате без окон не должно упираться в блокировку оверрайда"
    )


@pytest.mark.asyncio
async def test_room_with_windows_respects_lockout() -> None:
    """Комната с окнами: ручное действие по-прежнему важнее движения."""
    engine, dispatcher = _engine(room="spalnia", windowless=[ROOM])

    await engine.trigger(FSM_ID, "motion_detected")

    assert dispatcher.intents[0].bypass_lockout is False


@pytest.mark.asyncio
async def test_other_events_do_not_bypass_lockout() -> None:
    """Только движение: остальные события остаются под блокировкой."""
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    engine.register_definition(
        FSMDefinition(
            entity_id=FSM_ID,
            initial_state="ON_MOTION",
            states=("ON_MOTION", "OFF"),
            transitions=(
                Transition(
                    from_state="ON_MOTION",
                    to_state="OFF",
                    trigger="timeout",
                    action=_turn_on,  # type: ignore[arg-type]
                ),
            ),
            target_device_id="light.vykliuchatel_sanuzel_switch1",
            room=ROOM,
            params={"always_on_motion_rooms": [ROOM]},
        ),
        restore_state=False,
    )

    await engine.trigger(FSM_ID, "timeout")

    assert dispatcher.intents[0].bypass_lockout is False, (
        "обход блокировки — только у движения, а не у всех событий комнаты"
    )
