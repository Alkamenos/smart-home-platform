"""
WebSocket API для синхронизации состояния устройств в реальном времени.

T051-T052: Маршруты WebSocket для подписки на изменения состояния.
T071: Проверка доступа пользователя к устройствам.
"""

import asyncio
import contextlib
import json
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Хранилище активных WebSocket соединений
_active_connections: set[WebSocket] = set()


class WebSocketConnectionManager:
    """Менеджер для управления WebSocket соединениями.

    Хранит идентификацию (user_id) и подписки устройств на каждое соединение
    (ConnectionIdentity из data-model.md) для доставки событий по правам.
    """

    def __init__(self):
        """Инициализация менеджера."""
        self.active_connections: list[WebSocket] = []
        # ConnectionIdentity: соединение → идентификация и подписки
        self._identities: dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket):
        """Добавляет новое соединение.

        Args:
            websocket: WebSocket соединение
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Удаляет соединение вместе с идентификацией и подписками.

        Args:
            websocket: WebSocket соединение
        """
        with contextlib.suppress(ValueError):
            self.active_connections.remove(websocket)
        self._identities.pop(websocket, None)
        logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")

    def register_identity(self, websocket: WebSocket, user_id: str) -> None:
        """Связывает соединение с пользователем (auth-сообщение).

        Args:
            websocket: WebSocket соединение
            user_id: ID пользователя
        """
        identity = self._identities.setdefault(websocket, {"user_id": None, "devices": set()})
        identity["user_id"] = user_id

    def is_authenticated(self, websocket: WebSocket) -> bool:
        """Проверяет, аутентифицировано ли соединение.

        Args:
            websocket: WebSocket соединение

        Returns:
            True если есть user_id
        """
        identity = self._identities.get(websocket)
        return bool(identity and identity["user_id"])

    def add_subscription(self, websocket: WebSocket, device_id: str) -> None:
        """Добавляет подписку соединения на устройство.

        Args:
            websocket: WebSocket соединение
            device_id: ID устройства
        """
        identity = self._identities.setdefault(websocket, {"user_id": None, "devices": set()})
        identity["devices"].add(device_id)

    def remove_subscription(self, websocket: WebSocket, device_id: str) -> None:
        """Удаляет подписку соединения на устройство.

        Args:
            websocket: WebSocket соединение
            device_id: ID устройства
        """
        identity = self._identities.get(websocket)
        if identity:
            identity["devices"].discard(device_id)

    def is_subscribed(self, websocket: WebSocket, device_id: str) -> bool:
        """Проверяет подписку соединения на устройство.

        Args:
            websocket: WebSocket соединение
            device_id: ID устройства

        Returns:
            True если подписано
        """
        identity = self._identities.get(websocket)
        return bool(identity and device_id in identity["devices"])

    async def _has_access_now(self, connection: WebSocket, device_id: str, user_id: str) -> bool:
        """Проверяет доступ пользователя к устройству ПРЯМО СЕЙЧАС.

        Проверка выполняется при каждой доставке события (clarify Q1):
        отзыв доступа действует немедленно. Ошибки → безопасный deny.

        Args:
            connection: WebSocket соединение
            device_id: ID устройства (строка)
            user_id: ID пользователя

        Returns:
            True если доступ есть (роль viewer и выше)
        """
        try:
            app = connection.scope.get("app")
            service = getattr(app.state, "device_service", None) if app else None
            if service is None:
                return False
            return await service.check_device_access(UUID(device_id), user_id, "viewer")
        except Exception as e:
            logger.warning(f"Access check failed for {user_id} -> {device_id}: {e}")
            return False

    async def broadcast_device_event(self, device_id: str, message: dict):
        """Отправляет событие устройства только подписанным соединениям с доступом.

        Проверка доступа выполняется при каждой доставке (FR-008, clarify Q1).

        Args:
            device_id: ID устройства
            message: Сообщение для отправки
        """
        disconnected_clients = []

        for connection in list(self.active_connections):
            identity = self._identities.get(connection)
            if not identity or device_id not in identity["devices"]:
                continue
            if not identity["user_id"] or not await self._has_access_now(
                connection, device_id, identity["user_id"]
            ):
                continue
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to WebSocket: {e}")
                disconnected_clients.append(connection)

        for client in disconnected_clients:
            self.disconnect(client)

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
                    connection_manager.register_identity(websocket, user_id)
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
                    # T071/T016: проверяем доступ пользователя к устройству
                    # (роль viewer и выше) через DeviceService из app.state
                    has_access = False
                    try:
                        app = websocket.scope.get("app")
                        service = getattr(app.state, "device_service", None) if app else None
                        if service is not None:
                            has_access = await service.check_device_access(
                                UUID(device_id), user_id, required_role="viewer"
                            )
                    except ValueError as e:
                        logger.warning(f"Invalid device_id for access check: {device_id}: {e}")

                    if not has_access:
                        await connection_manager.send_personal(
                            websocket,
                            {
                                "type": "error",
                                "device_id": device_id,
                                "message": f"Access denied to device {device_id}",
                            },
                        )
                        logger.warning(f"Access denied: user {user_id} -> device {device_id}")
                        continue

                    connection_manager.add_subscription(websocket, device_id)
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
                if device_id and connection_manager.is_subscribed(websocket, device_id):
                    connection_manager.remove_subscription(websocket, device_id)
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
    """Отправляет изменение состояния подписанным соединениям с доступом.

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

    await connection_manager.broadcast_device_event(device_id, message)
    logger.debug(f"Broadcasted state change for device {device_id}")


def build_fsm_transition_message(payload: dict, device_id: str) -> dict | None:
    """Собрать сообщение о переходе автомата для клиента (FR-024).

    Args:
        payload: Полезная нагрузка события перехода.
        device_id: Идентификатор устройства (UUID), по которому клиенты
            подписываются.

    Returns:
        Сообщение для отправки либо None, если в событии нет состояния.
    """
    to_state = payload.get("to_state")
    fsm_id = payload.get("fsm_id")
    if not to_state or not fsm_id or not payload.get("device_id"):
        return None

    return {
        "type": "fsm_transition",
        "device_id": device_id,
        "fsm_id": fsm_id,
        "from_state": payload.get("from_state"),
        "state": to_state,
        "source": payload.get("source"),
        "timestamp": payload.get("timestamp"),
    }


def make_fsm_broadcaster(device_service: object | None):
    """Создать раздатчик переходов для моста состояний (T041).

    Событие перехода приходит с идентификатором устройства в формате Home
    Assistant (``light.kitchen``), а клиенты подписываются по внутреннему
    идентификатору устройства (UUID), поэтому требуется разрешение имён. Раздатчик
    получается как метод моста: он ничего не знает о способе доставки, что
    позволяет тестировать раздачу без веб-слоя.

    Args:
        device_service: Сервис устройств для разрешения идентификаторов.

    Returns:
        Асинхронный раздатчик, пригодный для ``FSMStateBridge.set_broadcaster``.
    """

    async def broadcast(payload: dict) -> None:
        entity_id = payload.get("device_id")
        if not entity_id or device_service is None:
            return

        device_uuid = await resolve_device_uuid(device_service, entity_id)
        if device_uuid is None:
            logger.debug(f"No device for FSM transition of {entity_id}; nothing to broadcast")
            return

        message = build_fsm_transition_message(payload, device_uuid)
        if message is None:
            return

        await connection_manager.broadcast_device_event(device_uuid, message)
        logger.debug(f"Broadcasted FSM transition for device {device_uuid}")

    return broadcast


async def resolve_device_uuid(device_service: object, entity_id: str) -> str | None:
    """Разрешить идентификатор устройства по entity_id Home Assistant.

    Args:
        device_service: Сервис устройств.
        entity_id: Идентификатор устройства в формате Home Assistant.

    Returns:
        Идентификатор устройства (UUID) либо None, если устройство не найдено.
    """
    try:
        devices = await device_service.get_all_devices()  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 - раздача не должна ломать переход
        logger.warning(f"Could not resolve device for {entity_id}: {e}")
        return None

    for device in devices:
        if device.ha_entity_id == entity_id:
            return str(device.id)
    return None
