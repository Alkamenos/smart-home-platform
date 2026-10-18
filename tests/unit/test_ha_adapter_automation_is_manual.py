"""Кнопка и автоматизация владельца — его интерфейс (B79/B91).

Решение владельца 2026-10-19: «кнопки это только интерфейс, управлять должна
платформа». Нажатие физической кнопки в этом доме вызывает автоматизацию Home
Assistant, а не команду платформы, поэтому у изменения состояния есть `parent_id`
(автоматизация) и нет `user_id`. Прежде платформа не видела в нажатии человека:
свет над рабочей поверхностью, включённый кнопкой, оставался гореть, потому что
модель продолжала считать его выключенным, а модификатор «мы спим» и истечение
оверрайда ни на что не влияли.

Границы проверки важны не меньше самой правки:

* изменение от автоматизации считается действием человека — платформа вошла в
  ручное состояние и вернётся к автоматике через срок оверрайда;
* **своя** команда платформы человеком не считается, даже если рядом оказался
  чужой `parent_id`;
* изменение прибора **без контекста** (настенный выключатель) человеком пока не
  считается: это отдельное решение по наблюдению B91 (до 20.10).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.ha_adapter import HAAdapter


#: Прибор, который владелец включает кнопкой (кухня, над рабочей поверхностью).
DEVICE = "light.svet_nad_rabochei_poverkhnostiu"

#: Идентификатор контекста собственной команды платформы.
OWN_CONTEXT = "01M4OWNCONTEXT0000000001"


class _ClientWithContext:
    """Клиент, отвечающий контекстом вызова, как это делает Home Assistant."""

    def __init__(self, context_id: str) -> None:
        self.context_id = context_id

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
    """Движок-двойник: помнит доставленные автоматам ручные события."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Автоматы прибора.

        Args:
            device_id: Идентификатор прибора.

        Returns:
            Список автоматов прибора.
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


def _adapter() -> tuple[HAAdapter, MagicMock, _Engine]:
    """Адаптер с настоящим middleware, движком-двойником и клиентом.

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
    adapter._ws_client = _ClientWithContext(OWN_CONTEXT)  # type: ignore[assignment]
    engine = _Engine()
    adapter._engine = engine  # type: ignore[assignment]
    return adapter, middleware.record_manual_control, engine


def _event(
    *,
    context_id: str | None,
    user_id: str | None = None,
    parent_id: str | None = None,
    old_state: str = "off",
    new_state: str = "on",
) -> dict[str, Any]:
    """Кадр `state_changed` с заданным контекстом.

    Args:
        context_id: Идентификатор контекста изменения.
        user_id: Пользователь в контексте либо None.
        parent_id: Родительский контекст (автоматизация) либо None.
        old_state: Прежнее состояние.
        new_state: Новое состояние.

    Returns:
        Данные события в форме, которую ждёт адаптер.
    """
    return {
        "entity_id": DEVICE,
        "old_state": {"state": old_state},
        "new_state": {"state": new_state},
        "context": {"id": context_id, "parent_id": parent_id, "user_id": user_id},
    }


class TestButtonIsAnInterface:
    """Нажатие кнопки доходит до платформы как решение человека."""

    @pytest.mark.asyncio
    async def test_automation_change_counts_as_human(self) -> None:
        """Автоматизация владельца: записан оверрайд и отправлено событие автомату."""
        adapter, record_manual, engine = _adapter()

        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id="01AUTOMATIONCHILD", parent_id="01AUTOMATION")
        )

        record_manual.assert_called_once_with(DEVICE)
        assert engine.events == [(f"{DEVICE}_lighting_10", "manual_switch_on")]

    @pytest.mark.asyncio
    async def test_own_command_is_not_human_even_with_parent(self) -> None:
        """Своя команда платформы не становится оверрайдом из-за чужого контекста."""
        adapter, record_manual, engine = _adapter()

        await adapter.call_service("light", "turn_on", DEVICE, {})
        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id=OWN_CONTEXT, parent_id="01AUTOMATION")
        )

        record_manual.assert_not_called()
        assert engine.events == []

    @pytest.mark.asyncio
    async def test_device_change_without_context_is_not_human_yet(self) -> None:
        """Настенный выключатель (без контекста) ждёт решения по B91."""
        adapter, record_manual, engine = _adapter()

        await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
            _event(context_id=None, parent_id=None)
        )

        record_manual.assert_not_called()
        assert engine.events == []
