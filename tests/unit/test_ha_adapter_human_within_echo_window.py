"""Человек, поправивший прибор сразу после нашей команды, засчитывается (B92).

У платформы свой пользователь Home Assistant (B45), поэтому `user_id` в контексте
изменения прямо говорит, кто действовал. Прежде действовало правило «мы недавно
командовали этому прибору — значит, изменение наше»: оно нужно интеграциям,
которые не возвращают контекст команды, но глушило и человека, успевшего
поправить прибор в те же 20 секунд. Свет возвращался, а блокировка против
автоматики не включалась.

Границы:

* чужой `user_id` — человек, даже внутри окна;
* свой `user_id` при недавней команде — эхо платформы, не человек;
* своего пользователя не знаем — прежнее правило (иначе первая же команда
  включала бы блокировку против себя, боевой случай 2026-10-08);
* без `user_id` и без автоматизации — действие прибора, человеком не считается
  (решение по наблюдению B91).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.ha_adapter import HAAdapter


DEVICE = "light.svet_nad_stolom"
PLATFORM_USER = "2f06091928aa4851adc10851dd791fda"
OWNER_USER = "ccbe96c151a248bd9c24e1d13d29c65d"
OWN_CONTEXT = "01M4OWNCONTEXT0000000001"


class _Client:
    """Клиент с контекстом команды, как его возвращает Home Assistant."""

    def __init__(self) -> None:
        self.context_id = OWN_CONTEXT

    async def call_service(self, **kwargs: Any) -> dict[str, Any]:
        """Вернуть контекст команды.

        Args:
            **kwargs: Параметры вызова сервиса.

        Returns:
            Ответ с контекстом вызова.
        """
        if kwargs.get("return_response") is False:
            return {"success": True}
        return {"context": {"id": self.context_id, "parent_id": None, "user_id": None}}


class _Engine:
    """Движок-двойник: помнит доставленные автоматам события."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Автоматы прибора.

        Args:
            device_id: Идентификатор прибора.

        Returns:
            Список автоматов.
        """
        return [f"{device_id}_lighting_10"]

    async def trigger(self, fsm_id: str, event: str, payload: dict[str, Any]) -> None:
        """Запомнить событие.

        Args:
            fsm_id: Автомат.
            event: Имя события.
            payload: Полезная нагрузка.
        """
        del payload
        self.events.append((fsm_id, event))


def _adapter(own_user_id: str | None) -> tuple[HAAdapter, MagicMock, _Engine]:
    """Адаптер с известным (или ещё нет) пользователем платформы.

    Args:
        own_user_id: Пользователь, которому принадлежит токен платформы
            (None — платформа его ещё не узнала).

    Returns:
        Адаптер, заглушка записи ручного действия и движок.
    """
    middleware = MagicMock()
    adapter = HAAdapter(
        mode="websocket",
        ws_url="ws://localhost:8123",
        token="test_token",
        manual_lockout_middleware=middleware,
    )
    adapter._ws_client = _Client()  # type: ignore[assignment]
    adapter._own_user_id = own_user_id  # noqa: SLF001 — предмет проверки
    engine = _Engine()
    adapter._engine = engine  # type: ignore[assignment]
    return adapter, middleware.record_manual_control, engine


def _event(*, context_id: str, user_id: str | None) -> dict[str, Any]:
    """Кадр `state_changed` с заданным контекстом.

    Args:
        context_id: Идентификатор контекста изменения.
        user_id: Пользователь в контексте.

    Returns:
        Данные события в форме, которую ждёт адаптер.
    """
    return {
        "entity_id": DEVICE,
        "old_state": {"state": "off"},
        "new_state": {"state": "on"},
        "context": {"id": context_id, "parent_id": None, "user_id": user_id},
    }


class TestHumanInsideEchoWindow:
    """Чужой пользователь — человек, даже в окне после нашей команды."""

    @pytest.mark.asyncio
    async def test_owner_action_after_our_command_is_manual(self) -> None:
        """Владелец включил свет сразу после нашей команды — это оверрайд."""
        adapter, record_manual, engine = _adapter(PLATFORM_USER)

        await adapter.call_service("light", "turn_off", DEVICE, {})
        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id="01HUMAN", user_id=OWNER_USER)
        )

        record_manual.assert_called_once_with(DEVICE)
        assert engine.events == [(f"{DEVICE}_lighting_10", "manual_switch_on")]

    @pytest.mark.asyncio
    async def test_own_echo_is_not_manual(self) -> None:
        """Наша команда с нашим пользователем — не человек."""
        adapter, record_manual, engine = _adapter(PLATFORM_USER)

        await adapter.call_service("light", "turn_on", DEVICE, {})
        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id=OWN_CONTEXT, user_id=PLATFORM_USER)
        )

        record_manual.assert_not_called()
        assert engine.events == []

    @pytest.mark.asyncio
    async def test_unknown_own_user_keeps_previous_rule(self) -> None:
        """Своего пользователя не знаем — прежнее правило, без самоблокировки."""
        adapter, record_manual, engine = _adapter(None)

        await adapter.call_service("light", "turn_on", DEVICE, {})
        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id="01HUMAN", user_id=OWNER_USER)
        )

        record_manual.assert_not_called()
        assert engine.events == []

    @pytest.mark.asyncio
    async def test_device_change_without_user_is_not_manual(self) -> None:
        """Действие прибора без пользователя человеком не считается (B91)."""
        adapter, record_manual, engine = _adapter(PLATFORM_USER)

        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id="01DEVICE", user_id=None)
        )

        record_manual.assert_not_called()
        assert engine.events == []


class TestOwnUserIsLearned:
    """Свой пользователь узнаётся из возврата собственной команды."""

    @pytest.mark.asyncio
    async def test_own_user_is_learned_from_own_echo(self) -> None:
        """Первый же возврат нашей команды даёт точное правило B92.

        Args:
            Нет.

        Returns:
            Ничего.
        """
        adapter, record_manual, _ = _adapter(None)

        await adapter.call_service("light", "turn_on", DEVICE, {})
        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id=OWN_CONTEXT, user_id=PLATFORM_USER)
        )

        assert adapter._own_user_id == PLATFORM_USER  # noqa: SLF001 — предмет проверки
        record_manual.assert_not_called()

        # Теперь человек, поправивший прибор в том же окне, — человек.
        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id="01HUMAN", user_id=OWNER_USER)
        )
        record_manual.assert_called_once_with(DEVICE)
