"""Ночное выключение не отменяется локаутом — иначе «не горит всю ночь» не выполнено.

Столкновение двух правил, оба из которых нужны владельцу:

- «человек главнее»: после ручного действия автоматика уступает на час;
- «свет не горит всю ночь»: в назначенный час платформа гасит свет сама.

Проверено в боре 2026-10-09 в 15:46: расписание сработало, команда ушла, но
локаут (созданный моим же включением света в 10:19) её отклонил — уличное
освещение осталось гореть. Если человек трогал свет вечером, он горел бы и всю
ночь, то есть второе правило просто не выполнялось.

Решение: выключение по часам — правило безопасности, а не удобство
автоматики, поэтому блокировку оно обходит. Всё остальное (движение,
расписания включения, локаут) по-прежнему человеку уступает.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker, TriggerSource
from core.models.manifest import AutomationDomainRules, AutomationRules
from core.scheduling.daily import DailyClock
from core.services.day_cycle import DayCycleService


class _Engine:
    """Движок-заглушка: достаточно знать, кому слать событие."""

    def __init__(self, recipients: list[str]) -> None:
        self._recipients = recipients
        self.sent: list[tuple[str, str]] = []

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Адресаты события.

        Args:
            trigger: Имя события.

        Returns:
            Список идентификаторов автоматов.
        """
        del trigger
        return list(self._recipients)

    async def trigger(self, entity_id: str, event: str, respect_debounce: bool = True) -> bool:
        """Отметить доставку события.

        Args:
            entity_id: Идентификатор автомата.
            event: Имя события.
            respect_debounce: Не используется в заглушке.

        Returns:
            Всегда True.
        """
        del respect_debounce
        self.sent.append((entity_id, event))
        return True


def _middleware_with_active_lockout() -> ManualLockoutMiddleware:
    """Middleware, у которого устройство только что трогал человек.

    Returns:
        Готовый middleware с действующей блокировкой.
    """
    tracker = ControlTracker(history_size=10)
    tracker.record("light.vse_fonari", TriggerSource.MANUAL, "manual_control")
    return ManualLockoutMiddleware(
        automation_rules=AutomationRules(
            global_manual_lockout_min=60,
            lighting=AutomationDomainRules(manual_lockout_min=60),
        ),
        control_tracker=tracker,
    )


class TestNightlyExtinguishIsNotBlockedByLockout:
    """Ночное выключение обходит блокировку, остальное — нет."""

    def test_lockout_is_active_before_the_test(self) -> None:
        """Проверка состояния: без действующей блокировка тест ничего не значит.

        Returns:
            Ничего.
        """
        middleware = _middleware_with_active_lockout()

        assert middleware._is_in_lockout_period(  # noqa: SLF001
            "light.vse_fonari", "light"
        ), "в проверке должна быть действующая блокировка"

    @pytest.mark.asyncio
    async def test_scheduled_command_bypasses_lockout(self) -> None:
        """Команда выключения по расписанию уходит, локаут её не отменяет.

        Returns:
            Ничего.
        """
        from core.commands.dispatcher import CommandIntent

        intent = CommandIntent(
            device_id="light.vse_fonari",
            domain="light",
            service="turn_off",
            data={},
            priority=50,
            source="lighting",
            bypass_lockout=True,
        )
        middleware = _middleware_with_active_lockout()

        result = await middleware.process(intent)

        assert result is not None, "ночное выключение отменено блокировкой — свет останется гореть"

    @pytest.mark.asyncio
    async def test_ordinary_command_still_respects_lockout(self) -> None:
        """Всё прочее по-прежнему уступает человеку.

        Returns:
            Ничего.
        """
        from core.commands.dispatcher import CommandIntent

        intent = CommandIntent(
            device_id="light.vse_fonari",
            domain="light",
            service="turn_on",
            data={},
            priority=50,
            source="lighting",
        )
        middleware = _middleware_with_active_lockout()

        result = await middleware.process(intent)

        assert result is None, "обычная команда прошла мимо блокировки"


class TestScheduledEventMarksItsCommand:
    """Событие расписания помечает команду как обходящую блокировку."""

    def test_quiet_hours_marks_command(self) -> None:
        """Действие, вызванное суточным событием, несёт пометку.

        Returns:
            Ничего.
        """
        intent = _turn_off({"bypass_lockout": True, "entity_id": "light.vse_fonari"})

        assert intent is not None
        assert intent.bypass_lockout is True, (
            "команда ночного выключения не помечена: блокировка её отменит"
        )

    def test_ordinary_action_has_no_mark(self) -> None:
        """Обычное действие помеченной не несёт.

        Returns:
            Ничего.
        """
        intent = _turn_off({"entity_id": "light.vse_fonari"})

        assert intent is not None
        assert intent.bypass_lockout is False

    @pytest.mark.asyncio
    async def test_cycle_reaches_the_right_automat(self) -> None:
        """Событие уходит только тем, кто умеет на него реагировать.

        Returns:
            Ничего.
        """
        clock = DailyClock(
            {dt.time(23, 0): "quiet_hours_started"},
            timezone=dt.UTC,
            now=lambda: dt.datetime.now(dt.UTC),
            sleep=lambda _s: __import__("asyncio").sleep(0),
        )
        engine = _Engine(["light.vse_fonari_lighting_10"])
        service = DayCycleService(clock=clock, engine=engine)  # type: ignore[arg-type]

        await service.handle("quiet_hours_started")

        assert engine.sent == [("light.vse_fonari_lighting_10", "quiet_hours_started")]


def _turn_off(context: dict[str, Any]) -> Any:
    """Команда выключения, собранная действием шаблона.

    Args:
        context: Контекст действия.

    Returns:
        Собранная команда либо None.
    """
    from core.action_handlers import turn_off_light

    return turn_off_light(None, context)
