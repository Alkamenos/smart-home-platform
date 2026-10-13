"""Канал живых изменений состояния для нового интерфейса (спека 017, FR-012).

Отдаёт изменения состояния сущностей Home Assistant (``state_change``), из
которых складываются показания локаций. Состояния автоматов остаются на канале
``/api/v1/ws/devices``: там подписка привязана к устройству и права проверяются
при каждой доставке, и переносить её сюда значило бы ослабить доступ.

Идентификация обязательна: соединение без ``auth`` не получает ничего
(fail-closed). Показания локаций — агрегированное наблюдение за домом, а не
управление прибором, поэтому отдельного фильтра по устройствам у них нет
(та же политика, что у HTTP-снимка локации, спека 016 FR-007).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

#: Темы подписки: показания датчиков/сущностей и состояния устройств из HA.
TOPIC_SENSORS = "locations"
TOPIC_DEVICES = "devices"

#: Сколько подписчиков темы получают изменение состояния сущности.
_DEFAULT_TOPICS = {TOPIC_SENSORS, TOPIC_DEVICES}


class EventStreamManager:
    """Подписки и доставка изменений состояния сущностей.

    Каждое соединение хранит идентичность и темы; сообщения уходят только
    авторизованным соединениям с подходящей темой.
    """

    def __init__(self) -> None:
        """Инициализация менеджера."""
        self._connections: dict[WebSocket, dict[str, Any]] = {}

    async def connect(self, websocket: WebSocket) -> None:
        """Принять соединение.

        Args:
            websocket: WebSocket-соединение.
        """
        await websocket.accept()
        self._connections[websocket] = {"user_id": None, "topics": set()}

    def disconnect(self, websocket: WebSocket) -> None:
        """Убрать соединение.

        Args:
            websocket: WebSocket-соединение.
        """
        self._connections.pop(websocket, None)

    def register_identity(self, websocket: WebSocket, user_id: str) -> None:
        """Связать соединение с пользователем.

        Args:
            websocket: WebSocket-соединение.
            user_id: Идентификатор пользователя.
        """
        state = self._connections.setdefault(websocket, {"user_id": None, "topics": set()})
        state["user_id"] = user_id

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """Проверить, что соединение авторизовано.

        Args:
            websocket: WebSocket-соединение.

        Returns:
            True, если у соединения есть пользователь.
        """
        state = self._connections.get(websocket)
        return bool(state and state["user_id"])

    def subscribe(self, websocket: WebSocket, topics: list[str]) -> set[str]:
        """Подписать соединение на темы.

        Args:
            websocket: WebSocket-соединение.
            topics: Запрошенные темы.

        Returns:
            Множество принятых тем.
        """
        state = self._connections.setdefault(websocket, {"user_id": None, "topics": set()})
        accepted = {topic for topic in topics if topic in _DEFAULT_TOPICS}
        if not accepted:
            accepted = set(_DEFAULT_TOPICS)
        state["topics"] = accepted
        return accepted

    async def broadcast_state_change(self, payload: dict[str, Any]) -> None:
        """Разослать изменение состояния подписчикам.

        Args:
            payload: Содержимое события шины (``entity_id``, ``new_state``,
                ``old_state``).
        """
        entity_id = payload.get("entity_id")
        if not entity_id:
            return
        message = {
            "type": "state_change",
            "entity_id": entity_id,
            "value": payload.get("new_state"),
            "old_value": payload.get("old_state"),
            "at": datetime.now(UTC).isoformat(),
        }
        await self._send_to_subscribers(message)

    async def _send_to_subscribers(self, message: dict[str, Any]) -> None:
        """Отправить сообщение подписанным авторизованным соединениям.

        Args:
            message: Сообщение для отправки.
        """
        dead: list[WebSocket] = []
        for connection, state in list(self._connections.items()):
            if not state.get("user_id"):
                continue
            if not (state.get("topics") or set()):
                continue
            try:
                await connection.send_json(message)
            except Exception as e:  # noqa: BLE001 - соединение могло закрыться
                logger.debug(f"Не удалось отправить в WebSocket: {e}")
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)


#: Единственный менеджер соединений на процесс.
event_stream = EventStreamManager()


async def on_state_change(event_type: str, payload: Any, trace_id: str | None = None) -> None:
    """Обработчик события шины ``state_change``.

    Args:
        event_type: Тип события (не используется, шина передаёт его первым).
        payload: Содержимое события.
        trace_id: Идентификатор трассы (не используется).
    """
    if not isinstance(payload, dict):
        return
    await event_stream.broadcast_state_change(payload)


@router.websocket("/api/v1/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Канал живых изменений состояния сущностей.

    Сообщения клиента:
    - ``{"type": "auth", "user_id": "..."}``
    - ``{"type": "subscribe", "topics": ["locations", "devices"]}``
    - ``{"type": "ping"}``

    Сообщения сервера:
    - ``{"type": "authenticated", ...}``
    - ``{"type": "subscribed", "topics": [...]}``
    - ``{"type": "state_change", "entity_id": ..., "value": ..., "at": ...}``
    - ``{"type": "pong"}`` / ``{"type": "error", ...}``
    """
    await event_stream.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                await websocket.send_json({"type": "error", "message": "Некорректный JSON"})
                continue

            msg_type = message.get("type")
            if msg_type == "auth":
                user_id = message.get("user_id")
                if not user_id:
                    await websocket.send_json({"type": "error", "message": "Нужен user_id"})
                    continue
                event_stream.register_identity(websocket, str(user_id))
                await websocket.send_json({"type": "authenticated", "user_id": str(user_id)})
            elif msg_type == "subscribe":
                if not event_stream.is_authenticated(websocket):
                    await websocket.send_json({"type": "error", "message": "Сначала auth"})
                    continue
                accepted = event_stream.subscribe(websocket, list(message.get("topics") or []))
                await websocket.send_json({"type": "subscribed", "topics": sorted(accepted)})
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        event_stream.disconnect(websocket)
    except Exception as e:  # noqa: BLE001 - закрытие соединения не должно валить сервер
        logger.debug(f"WebSocket events соединение закрыто: {e}")
        with contextlib.suppress(Exception):
            event_stream.disconnect(websocket)
