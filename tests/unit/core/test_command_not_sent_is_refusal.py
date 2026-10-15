"""Команда, не дошедшая до прибора, не считается выполненной (аудит 2026-10-16, К-2).

Боевой дефект класса «отказ выглядит как успех»: диспетчер отбрасывал результат
``call_service``, намерение оставалось активным, а автомат входил в «грею» или
«включено». Прибор при этом не получал ничего, и сторож молчал — автомат не завис,
он «сработал».

Проверка держит правило: **дома.** Не дошло — значит не выполнено.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import pytest

from core import CommandDispatcher, CommandIntent


class RefusingAdapter:
    """Адаптер, вызовы которому Home Assistant не подтверждает."""

    def __init__(self) -> None:
        """Собрать адаптер с пустой историей вызовов."""
        self.calls: list[tuple[str, str, str]] = []

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Записать вызов и ответить отказом.

        Args:
            domain: Домен сервиса.
            service: Имя сервиса.
            entity_id: Прибор.
            data: Данные вызова.
            trace_id: След.

        Returns:
            Всегда ``False`` — Home Assistant вызов не подтвердил.
        """
        del data, trace_id
        self.calls.append((domain, service, entity_id))
        return False

    async def get_state(self, entity_id: str) -> str | None:
        """Состояние прибора.

        Args:
            entity_id: Прибор.

        Returns:
            Всегда ``None``: дом не отвечает.
        """
        del entity_id
        return None


class ConfirmingAdapter(RefusingAdapter):
    """Адаптер, вызовы которому Home Assistant подтверждает."""

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Записать вызов и подтвердить его.

        Args:
            domain: Домен сервиса.
            service: Имя сервиса.
            entity_id: Прибор.
            data: Данные вызова.
            trace_id: След.

        Returns:
            ``True`` — вызов принят.
        """
        del data, trace_id
        self.calls.append((domain, service, entity_id))
        return True


def _intent() -> CommandIntent:
    """Намерение включить обогреватель.

    Returns:
        Намерение команды.
    """
    return CommandIntent(
        device_id="switch.obogrevatel_sanuzel",
        domain="switch",
        service="turn_on",
        data={},
        priority=10,
        source="climate_control",
    )


class TestCommandDeliveryIsNotAssumed:
    """Отправка команды и её выполнение — разные вещи."""

    @pytest.mark.asyncio
    async def test_refused_command_is_not_sent(self) -> None:
        """Не подтверждённый домом вызов — это невыполненная команда.

        Returns:
            Ничего.
        """
        adapter = RefusingAdapter()
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        sent = await dispatcher.submit(_intent())

        assert sent is False, (
            "недошедшая команда выдана за выполненную: автомат войдёт в «грею», "
            "журнал покажет выполнение, а прибор промолчит (аудит К-2)"
        )
        assert adapter.calls, "адаптер вообще не звали — проверять нечего"

    @pytest.mark.asyncio
    async def test_refused_command_releases_the_device(self) -> None:
        """Намерение не остаётся удерживать прибор, которому ничего не сказали.

        Returns:
            Ничего.
        """
        adapter = RefusingAdapter()
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        await dispatcher.submit(_intent())

        assert "switch.obogrevatel_sanuzel" not in dispatcher.active_intents, (
            "намерение осталось: диспетчер считает, что держит прибор, и мешает повторить"
        )

    @pytest.mark.asyncio
    async def test_confirmed_command_still_counts_as_sent(self) -> None:
        """Подтверждённый вызов по-прежнему считается отправленным.

        Returns:
            Ничего.
        """
        adapter = ConfirmingAdapter()
        dispatcher = CommandDispatcher(ha_adapter=adapter)

        sent = await dispatcher.submit(_intent())

        assert sent is True, "подтверждённая команда перестала считаться отправленной"
