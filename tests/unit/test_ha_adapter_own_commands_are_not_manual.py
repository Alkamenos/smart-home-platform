"""Свои команды платформы не должны считаться ручным действием.

Живой запуск 2026-10-08 вскрыл ровно то, чего не было видно в тени: команда
платформы уходит в Home Assistant по её собственному токену, и HA помечает
изменение состояния **тем же пользователем**, что и действия из приложения. То
есть собственная команда возвращается в адаптер как «человек выключил свет»:

    15:40:00 Accepted intent from websocket ... for device light.svet_nad_stolom
    15:40:00 Recorded manual control for device light.svet_nad_stolom

Следствие: первая же автоматическая команда включает блокировку против самой
себя на 60 минут. Дальше автоматика молчит, и дом остаётся под управлением
сценариев Home Assistant — молча, без единой записи об отказе.

Различить своё и чужое по конверту нельзя: `user_id` одинаковый. Но можно по
`context.id`: Home Assistant возвращает контекст каждого вызова сервиса, и
изменение состояния несёт тот же идентификатор. Свои контексты адаптер
запоминает и по ним ручным действием не считает.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.ha_adapter import HAAdapter
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from tests.helpers.ha_stub import state_changed_event


#: Устройство, которым платформа командует сама.
DEVICE = "light.svet_nad_stolom"

#: Идентификатор команды, который Home Assistant вернул адаптеру.
OWN_CONTEXT = "01M4OWNCONTEXT0000000001"


class _ClientWithContext:
    """Клиент, отвечающий контекстом вызова, как это делает Home Assistant."""

    def __init__(self, context_id: str) -> None:
        self.context_id = context_id
        self.calls: list[dict[str, Any]] = []

    async def call_service(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        if kwargs.get("return_response") is False:
            return {"success": True}
        return {"context": {"id": self.context_id, "parent_id": None, "user_id": None}}


class _ClientWithoutContext:
    """Клиент, не возвращающий контекст команды (боевой рекуператор Vakio)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call_service(self, **kwargs: Any) -> dict[str, Any]:
        """Вернуть ответ без контекста, как интеграция, которая его не шлёт."""
        self.calls.append(dict(kwargs))
        return {"changed_states": []}


def _adapter() -> tuple[HAAdapter, MagicMock, ControlTracker]:
    """Адаптер с настоящим middleware и клиентом, отдающим контекст.

    Returns:
        Адаптер, заглушка `record_manual_control` и трекер.
    """
    tracker = ControlTracker(history_size=10)
    middleware = ManualLockoutMiddleware(automation_rules=MagicMock(), control_tracker=tracker)
    middleware.record_manual_control = MagicMock()  # type: ignore[method-assign]
    adapter = HAAdapter(
        mode="websocket",
        ws_url="ws://localhost:8123",
        token="test_token",
        manual_lockout_middleware=middleware,
    )
    client = _ClientWithContext(OWN_CONTEXT)
    adapter._ws_client = client  # type: ignore[assignment]
    return adapter, middleware.record_manual_control, tracker


def _event(context_id: str | None, user_id: str | None) -> dict[str, Any]:
    """Кадр `state_changed` с заданным контекстом.

    Args:
        context_id: Идентификатор контекста в HA либо None.
        user_id: Пользователь в контексте либо None (устройство, человек).

    Returns:
        Данные события в форме, которую ждёт адаптер.
    """
    message = state_changed_event(DEVICE, new_state="on", old_state="off", user_id=user_id)
    event = message["event"]
    data = event["data"]
    context: dict[str, Any] = {"id": context_id, "parent_id": None, "user_id": user_id}
    return {
        "entity_id": data["entity_id"],
        "old_state": data["old_state"],
        "new_state": data["new_state"],
        "context": context,
    }


class TestOwnCommandIsNotManual:
    """Команда платформы не должна включать блокировку против самой платформы."""

    @pytest.mark.asyncio
    async def test_state_change_from_own_command_is_not_manual(self) -> None:
        """Событие с контекстом нашей команды — не ручное действие."""
        adapter, record_manual, _ = _adapter()

        await adapter.call_service("light", "turn_on", DEVICE, {})
        await adapter._handle_ws_state_change(_event(OWN_CONTEXT, "user-42"))

        record_manual.assert_not_called()

    @pytest.mark.asyncio
    async def test_state_change_from_other_source_still_manual(self) -> None:
        """Чужое изменение после окна — ручное действие остаётся.

        Returns:
            Ничего.
        """
        adapter, record_manual, _ = _adapter()

        await adapter.call_service("light", "turn_on", DEVICE, {})
        # Окно «мы командовали» истекает: изменение больше не наше.
        adapter._recent_commands[DEVICE] = time.monotonic() - 100  # noqa: SLF001
        await adapter._handle_ws_state_change(_event("01M4HUMANCONTEXT0000001", "user-42"))

        record_manual.assert_called_once_with(DEVICE)

    @pytest.mark.asyncio
    async def test_command_without_response_does_not_break_lockout(self) -> None:
        """Если HA не вернул контекст, чужое действие всё равно засчитывается.

        Иначе пришлось бы молчать о ручном вмешательстве всякий раз, когда
        ответ сервиса не долетел: платформа должна уступать человеку и при
        неполных данных, а не наоборот.
        """
        adapter, record_manual, _ = _adapter()
        adapter._ws_client = _ClientWithContext(OWN_CONTEXT)  # type: ignore[assignment]
        await adapter._ws_client.call_service(
            domain="light", service="turn_on", service_data={}, return_response=False
        )  # type: ignore[union-attr]

        await adapter._handle_ws_state_change(_event("01M4HUMANCONTEXT0000002", "user-42"))

        record_manual.assert_called_once_with(DEVICE)

    @pytest.mark.asyncio
    async def test_event_is_still_delivered_to_the_bus(self) -> None:
        """Своя команда — это не только «не ручное»: событие обязано дойти дальше.

        Иначе автомат перестал бы видеть состояние устройства после своей же
        команды, а интерфейс показывал бы устаревшее.
        """
        adapter, _, _ = _adapter()
        published: list[dict[str, Any]] = []

        class _Bus:
            """Шина, запоминающая публикации."""

            @property
            def event_bus(self) -> _Bus:
                return self

            async def publish(
                self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
            ) -> None:
                published.append({"event_type": event_type, "payload": payload})

        adapter._engine = _Bus()  # type: ignore[assignment]
        await adapter.call_service("light", "turn_on", DEVICE, {})
        await adapter._handle_ws_state_change(_event(OWN_CONTEXT, "user-42"))

        assert published, "событие своей команды не дошло до шины"


class TestOwnCommandWithoutContextIsNotManual:
    """Интеграция не несёт контекст команды — устройство всё равно «наше» (B49).

    Боевой рекуператор Vakio обновляет состояние так, что `context.id` команды
    до адаптера не доходит. Без окна «мы только что командовали» платформа
    принимала собственную команду за ручное действие (60-мин блокировка против
    себя), и прибор оставался на прежнем режиме — в бою 2026-10-13 в комнате
    было жарко, а рекуператор стоял на ночном минимуме 14 %.
    """

    @pytest.mark.asyncio
    async def test_recent_command_is_not_manual_without_own_context(self) -> None:
        """Чужой контекст в событии, но мы только что командовали — не ручное.

        Returns:
            Ничего.
        """
        adapter, record_manual, _ = _adapter()
        adapter._ws_client = _ClientWithoutContext()  # type: ignore[assignment]

        await adapter.call_service("fan", "set_preset_mode", DEVICE, {})
        await adapter._handle_ws_state_change(_event("01FOREIGNCONTEXT0000000001", "user-42"))

        record_manual.assert_not_called()

    @pytest.mark.asyncio
    async def test_manual_change_after_window_is_recorded(self) -> None:
        """Прошло больше окна — чужое изменение снова считается ручным.

        Returns:
            Ничего.
        """
        adapter, record_manual, _ = _adapter()
        adapter._recent_commands[DEVICE] = time.monotonic() - 100  # noqa: SLF001

        await adapter._handle_ws_state_change(_event("01FOREIGNCONTEXT0000000002", "user-42"))

        record_manual.assert_called_once_with(DEVICE)
