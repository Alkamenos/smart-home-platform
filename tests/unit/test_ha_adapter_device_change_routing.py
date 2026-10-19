"""Внешнее изменение состояния прибора доходит до маршрутизатора.

Рекуператор сам снимает «Приток MAX» примерно через пять минут. Событие об
этом приходит в адаптер (`state_changed`, `own=False`). Без отдельного вызова
маршрутизатор искал в нём только датчик, ничего не находил, и откат оставался
незамеченным до сторожа — в бою 2026-10-20 спальня дула «Рекуперацией (лето)»
на 100 % пять минут.

Проверяется развилка адаптера: **чужое** изменение прибора пересматривает его
автомат, а эхо собственной команды — нет (иначе каждая команда платформы
запускала бы лишний пересмотр и могла бы породить повторную команду).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from adapters.ha_adapter import HAAdapter
from tests.helpers.ha_stub import state_changed_event


DEVICE = "fan.base_smart"


class _Router:
    """Маршрутизатор-двойник: запоминает, что и куда дошло."""

    def __init__(self) -> None:
        self.sensor_calls: list[dict[str, Any]] = []
        self.device_calls: list[dict[str, Any]] = []

    async def route_state_change(self, **kwargs: Any) -> None:
        """Запомнить обычный маршрут датчика.

        Args:
            kwargs: Аргументы вызова.
        """
        self.sensor_calls.append(kwargs)

    async def route_device_change(self, **kwargs: Any) -> None:
        """Запомнить пересмотр по изменению прибора.

        Args:
            kwargs: Аргументы вызова.
        """
        self.device_calls.append(kwargs)


class _Client:
    """Минимальный клиент: адаптеру нужны только часы и «мы спим»."""

    daylight = False
    asleep = False


def _adapter() -> tuple[HAAdapter, _Router]:
    """Адаптер с маршрутизатором-двойником.

    Returns:
        Адаптер и маршрутизатор.
    """
    adapter = HAAdapter(mode="websocket", ws_url="ws://localhost:8123", token="token")
    router = _Router()
    adapter._event_router = router  # type: ignore[assignment]
    adapter._ws_client = _Client()  # type: ignore[assignment]
    return adapter, router


def _message(context_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Кадр `state_changed` для рекуператора.

    Args:
        context_id: Идентификатор контекста Home Assistant.
        user_id: Пользователь в контексте.

    Returns:
        Данные события в форме, которую ждёт адаптер.
    """
    message = state_changed_event(DEVICE, new_state="on", old_state="on", user_id=user_id)
    data = message["event"]["data"]
    return {
        "entity_id": data["entity_id"],
        "old_state": data["old_state"],
        "new_state": data["new_state"],
        "context": {"id": context_id, "parent_id": None, "user_id": user_id},
    }


class TestExternalDeviceChange:
    """Чужое изменение прибора — повод пересмотреть решение."""

    @pytest.mark.asyncio
    async def test_external_change_should_review_the_device_automaton(self) -> None:
        """Откат режима прибором доходит до маршрутизатора.

        Returns:
            Ничего.
        """
        adapter, router = _adapter()

        await adapter._handle_ws_state_change(_message("01FOREIGNCONTEXT000000001"))

        assert len(router.device_calls) == 1, (
            "прибор сам сменил режим, а пересмотра не было: «Приток MAX» "
            "останется снятым до следующего тика сторожа"
        )
        call = router.device_calls[0]
        assert call["entity_id"] == DEVICE
        assert call["new_state"] == "on"
        assert call["old_state"] == "on"


class TestOwnCommandEcho:
    """Эхо собственной команды не запускает второй пересмотр."""

    @pytest.mark.asyncio
    async def test_recent_command_should_not_review_the_device(self) -> None:
        """Своя команда в пределах окна — не повод для пересмотра.

        Returns:
            Ничего.
        """
        adapter, router = _adapter()
        adapter._recent_commands[DEVICE] = time.monotonic()  # noqa: SLF001

        await adapter._handle_ws_state_change(_message("01OURCOMMANDCONTEXT000001"))

        assert router.device_calls == [], (
            "эхо своей команды запустило пересмотр: лишняя команда и вспышка "
            "дисплея рекуператора (B95)"
        )
