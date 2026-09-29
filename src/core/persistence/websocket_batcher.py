"""
Батчер для синхронизации состояния при получении WebSocket событий.

Накапливает WebSocket события в буфер и обрабатывает их пакетами,
улучшая производительность при частых обновлениях состояния.

Принципы:
1. Батчинг по времени (100ms) или размеру (10 событий)
2. Объединение состояний для одного устройства (последнее значение побеждает)
3. Избежание дублирования обновлений
4. Thread-safe операции через asyncio.Lock
5. Асинхронная обработка с таймером срабатывания
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class WebSocketEvent:
    """Структура события WebSocket с информацией о состоянии устройства."""

    device_id: str
    """ID устройства (entity_id)"""

    state: str
    """Новое состояние"""

    attributes: dict[str, Any] = field(default_factory=dict)
    """Атрибуты состояния"""

    timestamp: float = field(default_factory=time.time)
    """Временная метка события"""

    source: str = "websocket"
    """Источник события"""

    def to_dict(self) -> dict[str, Any]:
        """Конвертировать событие в словарь."""
        return {
            "device_id": self.device_id,
            "state": self.state,
            "attributes": self.attributes,
            "timestamp": self.timestamp,
            "source": self.source,
        }


@dataclass
class WebSocketBatch:
    """Пакет объединённых событий для обработки."""

    events: dict[str, WebSocketEvent] = field(default_factory=dict)
    """Словарь device_id -> последнее событие для этого устройства"""

    batch_id: int = 0
    """ID пакета для отслеживания"""

    created_at: float = field(default_factory=time.time)
    """Время создания пакета"""

    def get_events_list(self) -> list[WebSocketEvent]:
        """Получить список событий в пакете."""
        return list(self.events.values())

    def size(self) -> int:
        """Получить количество событий в пакете."""
        return len(self.events)

    def to_dict(self) -> dict[str, Any]:
        """Конвертировать пакет в словарь."""
        return {
            "batch_id": self.batch_id,
            "created_at": self.created_at,
            "events": [event.to_dict() for event in self.get_events_list()],
            "size": self.size(),
        }


class WebSocketEventBatcher:
    """
    Батчер для группировки WebSocket событий синхронизации состояния.

    Накапливает события в буфер на период (100ms или 10 событий, что первое),
    затем обрабатывает их пакетами:
    - Объединяет состояния для одного устройства (последнее значение побеждает)
    - Избегает дублирования обновлений
    - Отправляет объединённый пакет на обновление

    Параметры:
        batch_timeout_ms: Таймаут для накопления событий (100ms по умолчанию)
        batch_size_limit: Максимальное количество уникальных устройств в пакете (10 по умолчанию)
        on_batch_ready: Callback функция для обработки готового пакета
    """

    def __init__(
        self,
        batch_timeout_ms: int = 100,
        batch_size_limit: int = 10,
        on_batch_ready: Callable[[WebSocketBatch], Any] | None = None,
        logger_instance: logging.Logger | None = None,
    ) -> None:
        """
        Инициализация батчера.

        Args:
            batch_timeout_ms: Таймаут в миллисекундах для накопления событий
            batch_size_limit: Максимальное количество уникальных устройств в пакете
            on_batch_ready: Callback для готового пакета
            logger_instance: Logger для отладки
        """
        self.batch_timeout_ms = batch_timeout_ms
        self.batch_size_limit = batch_size_limit
        self.on_batch_ready = on_batch_ready
        self._logger = logger_instance or logger

        # Буфер для накопления событий (device_id -> event)
        self._buffer: dict[str, WebSocketEvent] = {}

        # Lock для thread-safe операций
        self._lock = asyncio.Lock()

        # Таймер для срабатывания батча
        self._timer_task: asyncio.Task | None = None

        # Флаг активности батчера
        self._running = False

        # Счётчик пакетов для отслеживания
        self._batch_counter = 0

        # Статистика
        self._total_events = 0
        self._total_batches = 0
        self._last_batch_time = time.time()

    async def add_event(self, event: WebSocketEvent) -> None:
        """
        Добавить событие в буфер батчера.

        Если буфер переполнен по размеру, событие вызывает немедленную обработку.

        Args:
            event: Событие для добавления в батч
        """
        async with self._lock:
            # Добавляем событие в буфер (последнее значение для устройства побеждает)
            self._buffer[event.device_id] = event

            self._total_events += 1

            # Проверяем, нужно ли срабатывать батч по размеру
            if len(self._buffer) >= self.batch_size_limit:
                self._logger.debug(
                    f"Батч срабатывает по размеру: {len(self._buffer)} >= {self.batch_size_limit}"
                )
                await self._flush_batch()
            elif self._timer_task is None or self._timer_task.done():
                # Если таймер не установлен, запускаем его
                self._timer_task = asyncio.create_task(self._timeout_handler())

    async def flush(self) -> WebSocketBatch | None:
        """
        Принудительная обработка текущего батча.

        Используется при завершении работы или необходимости срочной обработки.

        Returns:
            Последний обработанный пакет или None если буфер пуст
        """
        async with self._lock:
            return await self._flush_batch()

    async def _flush_batch(self) -> WebSocketBatch | None:
        """
        Внутренняя функция для обработки батча (должна вызываться с активным lock).

        Returns:
            Обработанный пакет или None если буфер пуст
        """
        if not self._buffer:
            return None

        # Отменяем таймер если он активен
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._timer_task
            self._timer_task = None

        # Создаём пакет
        self._batch_counter += 1
        batch = WebSocketBatch(batch_id=self._batch_counter)

        # Перемещаем события из буфера в пакет
        batch.events = dict(self._buffer)
        self._buffer.clear()

        # Записываем статистику
        self._total_batches += 1
        self._last_batch_time = time.time()

        self._logger.debug(
            f"Пакет #{batch.batch_id} готов: {batch.size()} устройств, "
            f"всего событий обработано: {self._total_events}"
        )

        # Вызываем callback если установлен (без lock, чтобы не блокировать)
        if self.on_batch_ready:
            try:
                if asyncio.iscoroutinefunction(self.on_batch_ready):
                    # Не ждём асинхронный callback, чтобы не блокировать батчер
                    asyncio.create_task(self.on_batch_ready(batch))
                else:
                    # Синхронный callback вызываем напрямую
                    self.on_batch_ready(batch)
            except Exception as e:
                self._logger.error(f"Ошибка в callback батча: {e}", exc_info=True)

        return batch

    async def _timeout_handler(self) -> None:
        """
        Обработчик таймера для срабатывания батча по времени.

        Спит на duration timeout_ms, затем проверяет буфер.
        """
        try:
            # Конвертируем миллисекунды в секунды
            timeout_sec = self.batch_timeout_ms / 1000.0

            await asyncio.sleep(timeout_sec)

            async with self._lock:
                if self._buffer:
                    self._logger.debug(f"Батч срабатывает по таймауту: {len(self._buffer)} событий")
                    await self._flush_batch()

                # Очищаем таск
                self._timer_task = None

        except asyncio.CancelledError:
            # Таймер был отменён, ничего не делаем
            pass
        except Exception as e:
            self._logger.error(f"Ошибка в обработчике таймера: {e}", exc_info=True)

    def get_batch_size(self) -> int:
        """
        Получить текущий размер буфера (количество уникальных устройств).

        Returns:
            Количество событий в буфере
        """
        return len(self._buffer)

    def get_statistics(self) -> dict[str, Any]:
        """
        Получить статистику батчера.

        Returns:
            Словарь со статистикой:
            - total_events: Всего обработано событий
            - total_batches: Всего создано пакетов
            - current_buffer_size: Размер текущего буфера
            - last_batch_time: Время последнего пакета
            - uptime_sec: Время работы батчера
        """
        return {
            "total_events": self._total_events,
            "total_batches": self._total_batches,
            "current_buffer_size": self.get_batch_size(),
            "last_batch_time": self._last_batch_time,
            "avg_events_per_batch": (
                self._total_events / self._total_batches if self._total_batches > 0 else 0
            ),
        }

    async def start(self) -> None:
        """Запустить батчер (может использоваться для инициализации)."""
        async with self._lock:
            self._running = True
            self._logger.info(
                f"Батчер запущен: timeout={self.batch_timeout_ms}ms, "
                f"size_limit={self.batch_size_limit}"
            )

    async def stop(self) -> None:
        """
        Остановить батчер и обработать оставшиеся события.

        Вызывается при завершении работы, например при отключении WebSocket.
        """
        async with self._lock:
            self._running = False

            # Обрабатываем оставшиеся события
            if self._buffer:
                self._logger.info(
                    f"Остановка батчера: обработка {len(self._buffer)} оставшихся событий"
                )
                await self._flush_batch()

            # Отменяем таймер
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._timer_task

        self._logger.info(f"Батчер остановлен. Статистика: {self.get_statistics()}")

    async def reset(self) -> None:
        """Сбросить буфер без обработки (для очистки)."""
        async with self._lock:
            self._buffer.clear()
            self._total_events = 0
            self._total_batches = 0
            self._batch_counter = 0

            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()

            self._logger.debug("Батчер сброшен")
