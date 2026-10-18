"""Запись об изменении состояния обязана называть, кто его сделал.

Наблюдение за «светом над столом» (BACKLOG B91) требует ответа на вопрос «кто
выключил свет»: приложение, настенный выключатель или автоматизация. В контексте
Home Assistant это три разных случая:

- приложение — есть ``user_id``, нет ``parent_id``;
- автоматизация, сценарий или скрипт — есть ``parent_id``;
- прибор (настенный выключатель, кнопка) — нет ни того, ни другого.

Раньше в журнале контейнера была только строка «сущность: 'off' -> 'on'», и
отличить эти случаи задним числом было нельзя. Logbook Home Assistant здесь не
помогает: команда платформы несёт того же пользователя, что и приложение (урок
2026-10-08, ``test_ha_adapter_own_commands_are_not_manual``), поэтому «пользователь
в logbook» не доказывает, что свет гасил человек из приложения.

Отсюда три признака в строке: ``user=`` (кто), ``parent=`` (какая автоматизация
родила изменение), ``own=`` (это наша собственная команда вернулась).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.ha_adapter import HAAdapter


DEVICE = "light.svet_nad_stolom"

#: Идентификатор команды, который Home Assistant вернул адаптеру.
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


def _adapter() -> HAAdapter:
    """Адаптер с заглушкой middleware и клиентом, отдающим контекст.

    Returns:
        Готовый к вызову обработчика адаптер.
    """
    adapter = HAAdapter(
        mode="websocket",
        ws_url="ws://localhost:8123",
        token="test_token",
        manual_lockout_middleware=MagicMock(),
    )
    adapter._ws_client = _ClientWithContext(OWN_CONTEXT)  # type: ignore[assignment]
    return adapter


def _event(
    *,
    context_id: str | None,
    user_id: str | None,
    parent_id: str | None = None,
    old_state: str = "on",
    new_state: str = "off",
) -> dict[str, Any]:
    """Кадр `state_changed` с заданным контекстом.

    Args:
        context_id: Идентификатор контекста в HA либо None.
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


def _change_line(caplog: pytest.LogCaptureFixture) -> str:
    """Найти в захваченных записях строку об изменении состояния.

    Args:
        caplog: Захват журнала pytest.

    Returns:
        Текст строки ``HA STATE CHANGE``.
    """
    for record in caplog.records:
        if "HA STATE CHANGE" in record.getMessage():
            return record.getMessage()
    raise AssertionError("строка HA STATE CHANGE не записана")


class TestChangeLogNamesWhoChanged:
    """Строка изменения состояния различает человека, автоматизацию и прибор."""

    @pytest.mark.asyncio
    async def test_app_action_has_user(self, caplog: pytest.LogCaptureFixture) -> None:
        """Действие из приложения: есть пользователь, родителя нет."""
        adapter = _adapter()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
                _event(context_id="01HUMAN", user_id="user-42")
            )

        line = _change_line(caplog)
        assert "user=user-42" in line
        assert "parent=-" in line
        assert "own=False" in line

    @pytest.mark.asyncio
    async def test_automation_has_parent(self, caplog: pytest.LogCaptureFixture) -> None:
        """Автоматизация Home Assistant: есть родительский контекст, нет человека."""
        adapter = _adapter()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
                _event(context_id="01AUTO", user_id=None, parent_id="01AUTOMATION")
            )

        line = _change_line(caplog)
        assert "user=-" in line
        assert "parent=01AUTOMATION" in line
        assert "own=False" in line

    @pytest.mark.asyncio
    async def test_physical_switch_has_neither(self, caplog: pytest.LogCaptureFixture) -> None:
        """Настенный выключатель: ни пользователя, ни родителя.

        Это ровно тот случай, который невозможно отличить по logbook: в нём
        видно только пустого пользователя, как и у автоматизации.
        """
        adapter = _adapter()
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
                _event(context_id="01DEVICE", user_id=None, parent_id=None)
            )

        line = _change_line(caplog)
        assert "user=-" in line
        assert "parent=-" in line
        assert "own=False" in line

    @pytest.mark.asyncio
    async def test_own_command_is_marked(self, caplog: pytest.LogCaptureFixture) -> None:
        """Возврат собственной команды помечается ``own=True``.

        Без этой пометки «пользователь в контексте» снова читается как человек:
        собственная команда платформы несёт того же пользователя, что и
        приложение.
        """
        adapter = _adapter()
        await adapter.call_service("light", "turn_on", DEVICE, {})
        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await adapter._handle_ws_state_change(  # noqa: SLF001 — предмет проверки
                _event(context_id=OWN_CONTEXT, user_id="user-42", old_state="off", new_state="on")
            )

        line = _change_line(caplog)
        assert "own=True" in line
