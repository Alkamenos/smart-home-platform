"""
WebSocket клиент для синхронизации состояния устройств в реальном времени.

Обеспечивает подписку на события изменения состояния в Home Assistant.
Использует батчинг для улучшения производительности при частых обновлениях.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp
from pydantic import HttpUrl

from core.persistence.websocket_batcher import WebSocketEvent, WebSocketEventBatcher


logger = logging.getLogger(__name__)


class HAWebSocketClient:
    """WebSocket клиент для подписки на события Home Assistant в реальном времени."""

    def __init__(
        self,
        base_url: HttpUrl | str,
        token: str,
        on_state_changed: Callable[[dict[str, Any]], None] | None = None,
        batch_timeout_ms: int = 100,
        batch_size_limit: int = 10,
        enable_batching: bool = True,
    ) -> None:
        """Инициализация WebSocket клиента.

        Args:
            base_url: URL экземпляра Home Assistant
            token: Long-lived access token для аутентификации
            on_state_changed: Callback функция для обработки события изменения состояния
            batch_timeout_ms: Таймаут для батчинга в миллисекундах (100ms по умолчанию)
            batch_size_limit: Максимальный размер батча (10 по умолчанию)
            enable_batching: Включить батчинг событий (True по умолчанию)
        """
        self.base_url = str(base_url).rstrip("/")
        self.token = token
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.on_state_changed = on_state_changed
        self._running = False
        self._message_id = 1
        self._subscription_id: int | None = None

        # Инициализация батчера
        self._batcher: WebSocketEventBatcher | None = None
        self._enable_batching = enable_batching
        self._batch_timeout_ms = batch_timeout_ms
        self._batch_size_limit = batch_size_limit

        if enable_batching:
            self._batcher = WebSocketEventBatcher(
                batch_timeout_ms=batch_timeout_ms,
                batch_size_limit=batch_size_limit,
                on_batch_ready=self._process_batch,
                logger_instance=logger,
            )

    async def connect(self) -> bool:
        """Подключается к WebSocket серверу Home Assistant.

        Returns:
            True если подключение успешно
        """
        try:
            # Преобразуем http/https URL в ws/wss
            ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            ws_url = f"{ws_url}/api/websocket"

            session = aiohttp.ClientSession()
            self.ws = await session.ws_connect(
                ws_url,
                heartbeat=30,
            )

            # Выполняем аутентификацию
            auth_message = {
                "type": "auth",
                "access_token": self.token,
            }
            await self.ws.send_json(auth_message)

            # Получаем ответ на аутентификацию
            auth_response = await self.ws.receive_json()
            if auth_response.get("type") == "auth_ok":
                logger.info("WebSocket аутентификация успешна")
                self._running = True
                return True
            else:
                logger.error(f"Ошибка аутентификации: {auth_response}")
                return False

        except Exception as e:
            logger.error(f"Ошибка подключения к WebSocket: {e}")
            return False

    async def subscribe_to_state_changes(self) -> bool:
        """Подписывается на события изменения состояния.

        Returns:
            True если подписка успешна
        """
        if not self.ws:
            logger.error("WebSocket не подключен")
            return False

        try:
            self._message_id += 1
            subscribe_message = {
                "id": self._message_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }

            await self.ws.send_json(subscribe_message)
            response = await self.ws.receive_json()

            if response.get("type") == "result" and response.get("success"):
                self._subscription_id = response.get("id")
                logger.info("Подписка на события state_changed установлена")
                return True
            else:
                logger.error(f"Ошибка подписки: {response}")
                return False

        except Exception as e:
            logger.error(f"Ошибка при подписке на события: {e}")
            return False

    async def listen(self) -> None:
        """Слушает события с WebSocket.

        Блокирующая функция, должна вызываться в отдельной асинхронной задаче.
        Использует батчинг для группировки событий перед обработкой.
        """
        if not self.ws or not self._running:
            logger.error("WebSocket не активен")
            return

        # Запускаем батчер если он включен
        if self._batcher:
            await self._batcher.start()

        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        event = json.loads(msg.data)
                        if event.get("type") == "event":
                            event_data = event.get("event", {})
                            if event_data.get("event_type") == "state_changed":
                                logger.debug(f"Получено событие: {event_data}")

                                # Обрабатываем событие через батчер или напрямую
                                if self._batcher:
                                    await self._process_state_changed_batched(event_data)
                                elif self.on_state_changed:
                                    await self._call_callback(self.on_state_changed, event_data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Ошибка парсинга JSON: {e}")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket ошибка: {self.ws.exception()}")
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("WebSocket соединение закрыто")
                    break

        except Exception as e:
            logger.error(f"Ошибка при прослушивании WebSocket: {e}")
        finally:
            self._running = False
            # Останавливаем батчер при отключении
            if self._batcher:
                await self._batcher.stop()

    async def _process_state_changed_batched(self, event_data: dict[str, Any]) -> None:
        """
        Обработать событие изменения состояния через батчер.

        Args:
            event_data: Данные события от Home Assistant
        """
        if not self._batcher:
            return

        try:
            # Извлекаем информацию из события
            new_state = event_data.get("new_state", {})
            entity_id = new_state.get("entity_id", "unknown")
            state = new_state.get("state", "unknown")
            attributes = new_state.get("attributes", {})

            # Создаём событие для батчера
            ws_event = WebSocketEvent(
                device_id=entity_id,
                state=state,
                attributes=attributes,
                source="websocket",
            )

            # Добавляем в батчер
            await self._batcher.add_event(ws_event)

        except Exception as e:
            logger.error(f"Ошибка при обработке события батчером: {e}", exc_info=True)

    async def _process_batch(self, batch) -> None:
        """
        Обработать готовый пакет событий.

        Вызывается батчером когда пакет готов к отправке.

        Args:
            batch: WebSocketBatch объект с объединёнными событиями
        """
        try:
            logger.debug(f"Обработка пакета #{batch.batch_id} с {batch.size()} событиями")

            # Если есть callback, вызываем его с объединённым пакетом
            if self.on_state_changed:
                # Конвертируем пакет в формат, понятный callback
                batch_dict = batch.to_dict()
                await self._call_callback(self.on_state_changed, batch_dict)

        except Exception as e:
            logger.error(f"Ошибка при обработке пакета: {e}", exc_info=True)

    def get_batcher(self) -> WebSocketEventBatcher | None:
        """
        Получить батчер для доступа к статистике и управлению.

        Returns:
            Объект батчера или None если батчинг отключен
        """
        return self._batcher

    def get_batch_statistics(self) -> dict[str, Any]:
        """
        Получить статистику батчера.

        Returns:
            Словарь со статистикой батчера
        """
        if self._batcher:
            return self._batcher.get_statistics()
        return {}

    async def _call_callback(self, callback: Callable, event_data: dict[str, Any]) -> None:
        """Безопасно вызывает callback функцию.

        Args:
            callback: Функция для вызова
            event_data: Данные события
        """
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(event_data)
            else:
                callback(event_data)
        except Exception as e:
            logger.error(f"Ошибка в callback: {e}")

    async def disconnect(self) -> None:
        """Отключается от WebSocket сервера."""
        self._running = False

        # Останавливаем батчер
        if self._batcher:
            await self._batcher.stop()

        if self.ws:
            await self.ws.close()
            logger.info("WebSocket соединение закрыто")
