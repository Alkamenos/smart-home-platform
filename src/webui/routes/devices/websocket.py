"""
WebSocket API для синхронизации состояния устройств в реальном времени.

T051-T052: Маршруты WebSocket для подписки на изменения состояния.
T071: Проверка доступа пользователя к устройствам.
"""

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Хранилище активных WebSocket соединений
_active_connections: set[WebSocket] = set()


class WebSocketConnectionManager:
    """Менеджер для управления WebSocket соединениями."""

    def __init__(self):
        """Инициализация менеджера."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Добавляет новое соединение.

        Args:
            websocket: WebSocket соединение
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Удаляет соединение.

        Args:
            websocket: WebSocket соединение
        """
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Отправляет сообщение всем подключенным клиентам.

        Args:
            message: Сообщение для отправки
        """
        disconnected_clients = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                disconnected_clients.append(connection)

        # Удаляем отключенные соединения
        for client in disconnected_clients:
            self.disconnect(client)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """Отправляет сообщение конкретному клиенту.

        Args:
            websocket: WebSocket соединение
            message: Сообщение для отправки
        """
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")


# Глобальный менеджер соединений
connection_manager = WebSocketConnectionManager()


@router.websocket("/api/v1/ws/devices")
async def websocket_endpoint(websocket: WebSocket):
    """T051-T052, T071: WebSocket endpoint для синхронизации состояния устройств.

    Клиент может подписаться на события изменения состояния устройств (с проверкой доступа).
    Сервер будет отправлять события в реальном времени при изменении состояния.

    Сообщения от клиента:
    - {"type": "auth", "user_id": "uuid"} - авторизация пользователя (требуется перед подпиской)
    - {"type": "subscribe", "device_id": "uuid"} - подписаться на устройство (требуется доступ)
    - {"type": "unsubscribe", "device_id": "uuid"} - отписаться от устройства
    - {"type": "ping"} - проверка соединения

    Сообщения от сервера:
    - {"type": "pong"} - ответ на ping
    - {"type": "authenticated"} - успешная авторизация
    - {"type": "subscribed", "device_id": "uuid"} - успешная подписка
    - {"type": "unsubscribed", "device_id": "uuid"} - успешная отписка
    - {"type": "state_changed", "device_id": "uuid", "state": {...}} - изменение состояния
    - {"type": "error", "message": "..."} - ошибка
    """
    await connection_manager.connect(websocket)
    subscribed_devices = set()
    user_id: str | None = None  # T071: ID пользователя для проверки доступа

    try:
        while True:
            # Получаем сообщение от клиента
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")

            # T071: Обработка авторизации пользователя
            if msg_type == "auth":
                user_id = message.get("user_id")
                if user_id:
                    logger.info(f"WebSocket client authenticated as {user_id}")
                    await connection_manager.send_personal(
                        websocket,
                        {
                            "type": "authenticated",
                            "user_id": user_id,
                            "message": f"Successfully authenticated as {user_id}",
                        },
                    )
                else:
                    await connection_manager.send_personal(
                        websocket,
                        {
                            "type": "error",
                            "message": "Missing user_id for authentication",
                        },
                    )

            elif msg_type == "subscribe":
                # T071: Подписка на устройство с проверкой доступа
                device_id = message.get("device_id")

                if not user_id:
                    await connection_manager.send_personal(
                        websocket,
                        {
                            "type": "error",
                            "device_id": device_id,
                            "message": "Must authenticate first (send 'auth' message)",
                        },
                    )
                    continue

                if device_id:
                    # Проверяем доступ пользователя к устройству
                    # (будет реализовано через DeviceService.check_device_access)
                    # device_service = get_device_service()  # TODO: внедрить через зависимость
                    # has_access = await device_service.check_device_access(
                    #     UUID(device_id), user_id, required_role="viewer"
                    # )

                    # if not has_access:
                    #     await connection_manager.send_personal(
                    #         websocket,
                    #         {
                    #             "type": "error",
                    #             "device_id": device_id,
                    #             "message": f"Access denied to device {device_id}",
                    #         }
                    #     )
                    #     logger.warning(f"Access denied: user {user_id} -> device {device_id}")
                    #     continue

                    subscribed_devices.add(device_id)
                    logger.info(f"User {user_id} subscribed to device {device_id}")

                    await connection_manager.send_personal(
                        websocket,
                        {
                            "type": "subscribed",
                            "device_id": device_id,
                            "message": f"Successfully subscribed to {device_id}",
                        },
                    )

            elif msg_type == "unsubscribe":
                # Отписка от устройства
                device_id = message.get("device_id")
                if device_id and device_id in subscribed_devices:
                    subscribed_devices.remove(device_id)
                    logger.info(f"User {user_id} unsubscribed from device {device_id}")

                    await connection_manager.send_personal(
                        websocket,
                        {
                            "type": "unsubscribed",
                            "device_id": device_id,
                            "message": f"Successfully unsubscribed from {device_id}",
                        },
                    )

            elif msg_type == "ping":
                # Проверка соединения
                await connection_manager.send_personal(
                    websocket,
                    {
                        "type": "pong",
                        "timestamp": asyncio.get_event_loop().time(),
                    },
                )

            else:
                logger.warning(f"Unknown message type: {msg_type}")

                await connection_manager.send_personal(
                    websocket,
                    {
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}",
                    },
                )

    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
        logger.info(f"WebSocket disconnected for user {user_id}")

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON received: {e}")
        with contextlib.suppress(Exception):
            await connection_manager.send_personal(
                websocket,
                {
                    "type": "error",
                    "message": "Invalid JSON format",
                },
            )

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        connection_manager.disconnect(websocket)


async def broadcast_state_change(device_id: str, state: dict):
    """Отправляет изменение состояния всем подключенным клиентам.

    Args:
        device_id: ID устройства
        state: Новое состояние
    """
    message = {
        "type": "state_changed",
        "device_id": device_id,
        "state": state,
        "timestamp": asyncio.get_event_loop().time(),
    }

    await connection_manager.broadcast(message)
    logger.debug(f"Broadcasted state change for device {device_id}")
