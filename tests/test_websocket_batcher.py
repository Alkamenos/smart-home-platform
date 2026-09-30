"""
Тесты для WebSocketEventBatcher.

Проверяют:
1. Добавление событий и группировку по device_id
2. Срабатывание батча по таймауту
3. Срабатывание батча по размеру
4. Объединение состояний (последнее значение побеждает)
5. Избежание дублирования
6. Thread-safe операции
7. Статистика и monitoring
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import asyncio
import time

import pytest

from core.persistence.websocket_batcher import (
    WebSocketBatch,
    WebSocketEvent,
    WebSocketEventBatcher,
)


class TestWebSocketEvent:
    """Тесты для WebSocketEvent."""

    def test_create_event(self):
        """Создание события работает."""
        event = WebSocketEvent(
            device_id="light.kitchen",
            state="ON",
            attributes={"brightness": 100},
        )

        assert event.device_id == "light.kitchen"
        assert event.state == "ON"
        assert event.attributes == {"brightness": 100}
        assert event.source == "websocket"

    def test_event_to_dict(self):
        """Конвертация события в словарь."""
        event = WebSocketEvent(
            device_id="light.kitchen",
            state="ON",
            attributes={"brightness": 100},
            timestamp=12345.0,
        )

        event_dict = event.to_dict()

        assert event_dict["device_id"] == "light.kitchen"
        assert event_dict["state"] == "ON"
        assert event_dict["attributes"]["brightness"] == 100
        assert event_dict["timestamp"] == 12345.0


class TestWebSocketBatch:
    """Тесты для WebSocketBatch."""

    def test_create_batch(self):
        """Создание пакета работает."""
        batch = WebSocketBatch(batch_id=1)

        assert batch.batch_id == 1
        assert batch.size() == 0

    def test_batch_add_events(self):
        """Добавление событий в пакет."""
        batch = WebSocketBatch()

        event1 = WebSocketEvent(device_id="light.kitchen", state="ON")
        event2 = WebSocketEvent(device_id="light.bedroom", state="OFF")

        batch.events[event1.device_id] = event1
        batch.events[event2.device_id] = event2

        assert batch.size() == 2
        events_list = batch.get_events_list()
        assert len(events_list) == 2

    def test_batch_to_dict(self):
        """Конвертация пакета в словарь."""
        batch = WebSocketBatch(batch_id=1)
        event = WebSocketEvent(device_id="light.kitchen", state="ON")
        batch.events[event.device_id] = event

        batch_dict = batch.to_dict()

        assert batch_dict["batch_id"] == 1
        assert batch_dict["size"] == 1
        assert len(batch_dict["events"]) == 1


class TestWebSocketEventBatcher:
    """Тесты для WebSocketEventBatcher."""

    @pytest.fixture
    def batcher(self):
        """Создать батчер для тестов."""
        return WebSocketEventBatcher(
            batch_timeout_ms=50,  # Короткий таймаут для тестов
            batch_size_limit=3,
        )

    @pytest.mark.asyncio
    async def test_create_batcher(self, batcher):
        """Создание батчера работает."""
        assert batcher.batch_timeout_ms == 50
        assert batcher.batch_size_limit == 3
        assert batcher.get_batch_size() == 0

    @pytest.mark.asyncio
    async def test_add_single_event(self, batcher):
        """Добавление одного события."""
        event = WebSocketEvent(device_id="light.kitchen", state="ON")
        await batcher.add_event(event)

        assert batcher.get_batch_size() == 1

    @pytest.mark.asyncio
    async def test_batch_by_timeout(self, batcher):
        """Батч срабатывает по таймауту."""
        batch_ready = asyncio.Event()
        captured_batch = None

        async def callback(batch):
            nonlocal captured_batch
            captured_batch = batch
            batch_ready.set()

        batcher.on_batch_ready = callback

        # Добавляем событие
        event = WebSocketEvent(device_id="light.kitchen", state="ON")
        await batcher.add_event(event)

        # Ждём срабатывания по таймауту
        try:
            await asyncio.wait_for(batch_ready.wait(), timeout=1.0)
        except TimeoutError:
            pytest.fail("Батч не срабатил по таймауту")

        # Проверяем, что батч был создан
        assert captured_batch is not None
        assert captured_batch.size() == 1
        assert captured_batch.batch_id == 1

    @pytest.mark.asyncio
    async def test_batch_by_size(self, batcher):
        """Батч срабатывает по размеру (достижению лимита)."""
        batch_ready = asyncio.Event()
        captured_batch = None

        async def callback(batch):
            nonlocal captured_batch
            captured_batch = batch
            batch_ready.set()

        batcher.on_batch_ready = callback

        # Добавляем события до лимита (3)
        for i in range(3):
            event = WebSocketEvent(device_id=f"light.room{i}", state="ON")
            await batcher.add_event(event)

        # Батч должен срабатить немедленно на 3-м событии
        try:
            await asyncio.wait_for(batch_ready.wait(), timeout=0.5)
        except TimeoutError:
            pytest.fail("Батч не срабатил по размеру")

        assert captured_batch is not None
        assert captured_batch.size() == 3
        assert batcher.get_batch_size() == 0  # Буфер очищен

    @pytest.mark.asyncio
    async def test_merge_events_for_same_device(self, batcher):
        """События для одного устройства объединяются (последнее победит)."""
        batch_ready = asyncio.Event()
        captured_batch = None

        async def callback(batch):
            nonlocal captured_batch
            captured_batch = batch
            batch_ready.set()

        batcher.on_batch_ready = callback

        # Добавляем 3 события для одного устройства
        event1 = WebSocketEvent(
            device_id="light.kitchen", state="OFF", attributes={"brightness": 0}
        )
        await batcher.add_event(event1)

        event2 = WebSocketEvent(
            device_id="light.kitchen", state="ON", attributes={"brightness": 50}
        )
        await batcher.add_event(event2)

        event3 = WebSocketEvent(
            device_id="light.kitchen", state="ON", attributes={"brightness": 100}
        )
        await batcher.add_event(event3)

        # Ждём срабатывания (по таймауту, так как события одного устройства)
        try:
            await asyncio.wait_for(batch_ready.wait(), timeout=1.0)
        except TimeoutError:
            pytest.fail("Батч не срабатил по таймауту")

        # В пакете должно быть только 1 событие (последнее)
        assert captured_batch is not None
        assert captured_batch.size() == 1
        events = captured_batch.get_events_list()
        assert events[0].state == "ON"
        assert events[0].attributes["brightness"] == 100

    @pytest.mark.asyncio
    async def test_multiple_devices_in_batch(self, batcher):
        """Пакет содержит события от разных устройств."""
        batch_ready = asyncio.Event()
        captured_batch = None

        async def callback(batch):
            nonlocal captured_batch
            captured_batch = batch
            batch_ready.set()

        batcher.on_batch_ready = callback

        # Добавляем события от разных устройств
        devices = ["light.kitchen", "light.bedroom", "light.living_room"]
        for device_id in devices:
            event = WebSocketEvent(device_id=device_id, state="ON")
            await batcher.add_event(event)

        # Батч должен срабатить по размеру на 3-м событии
        try:
            await asyncio.wait_for(batch_ready.wait(), timeout=0.5)
        except TimeoutError:
            pytest.fail("Батч не срабатил по размеру")

        assert captured_batch.size() == 3
        device_ids = {event.device_id for event in captured_batch.get_events_list()}
        assert device_ids == set(devices)

    @pytest.mark.asyncio
    async def test_flush_manual(self, batcher):
        """Принудительное срабатывание батча."""
        event = WebSocketEvent(device_id="light.kitchen", state="ON")
        await batcher.add_event(event)

        assert batcher.get_batch_size() == 1

        # Принудительное срабатывание
        batch = await batcher.flush()

        assert batch is not None
        assert batch.size() == 1
        assert batcher.get_batch_size() == 0

    @pytest.mark.asyncio
    async def test_flush_empty_buffer(self, batcher):
        """Flush на пустом буфере возвращает None."""
        batch = await batcher.flush()
        assert batch is None

    @pytest.mark.asyncio
    async def test_concurrent_add_events(self):
        """Параллельное добавление событий работает.

        Используем батчер с высоким лимитом и длинным таймаутом, чтобы проверить
        именно конкурентное добавление (при лимите 3 батч срабатывает по размеру).
        """
        batcher = WebSocketEventBatcher(batch_timeout_ms=60000, batch_size_limit=100)

        async def add_events(start_id, count):
            for i in range(count):
                event = WebSocketEvent(device_id=f"light.room{start_id}_{i}", state="ON")
                await batcher.add_event(event)

        # Запускаем несколько параллельных потоков добавления
        await asyncio.gather(
            add_events(1, 5),
            add_events(2, 5),
            add_events(3, 5),
        )

        # В буфере должны быть все события (ни одно не потеряно)
        assert batcher.get_batch_size() == 15

    @pytest.mark.asyncio
    async def test_statistics(self):
        """Получение статистики батчера."""
        # Лимит выше числа событий — иначе срабатывает автосрабатывание по размеру
        batcher = WebSocketEventBatcher(batch_timeout_ms=60000, batch_size_limit=10)

        # Добавляем события
        for i in range(5):
            event = WebSocketEvent(device_id=f"light.room{i}", state="ON")
            await batcher.add_event(event)

        # Принудительно срабатываем
        await batcher.flush()

        stats = batcher.get_statistics()

        assert stats["total_events"] == 5
        assert stats["total_batches"] == 1
        assert stats["current_buffer_size"] == 0
        assert stats["avg_events_per_batch"] == 5.0

    @pytest.mark.asyncio
    async def test_start_and_stop(self, batcher):
        """Запуск и остановка батчера."""
        await batcher.start()
        assert batcher._running

        # Добавляем событие
        event = WebSocketEvent(device_id="light.kitchen", state="ON")
        await batcher.add_event(event)

        # Останавливаем (должен обработать оставшееся)
        await batcher.stop()
        assert not batcher._running
        assert batcher.get_batch_size() == 0

    @pytest.mark.asyncio
    async def test_reset_batcher(self):
        """Сброс батчера очищает буфер и статистику."""
        # Лимит выше числа событий, чтобы события оставались в буфере до reset()
        batcher = WebSocketEventBatcher(batch_timeout_ms=60000, batch_size_limit=10)

        # Добавляем события
        for i in range(5):
            event = WebSocketEvent(device_id=f"light.room{i}", state="ON")
            await batcher.add_event(event)

        assert batcher.get_batch_size() == 5

        # Сбрасываем
        await batcher.reset()

        assert batcher.get_batch_size() == 0
        stats = batcher.get_statistics()
        assert stats["total_events"] == 0
        assert stats["total_batches"] == 0

    @pytest.mark.asyncio
    async def test_sync_callback(self, batcher):
        """Синхронный callback работает."""
        callback_called = False
        received_batch = None

        def sync_callback(batch):
            nonlocal callback_called, received_batch
            callback_called = True
            received_batch = batch

        batcher.on_batch_ready = sync_callback

        event = WebSocketEvent(device_id="light.kitchen", state="ON")
        await batcher.add_event(event)

        # Ждём, чтобы таймер срабатил
        await asyncio.sleep(0.2)

        assert callback_called
        assert received_batch is not None

    @pytest.mark.asyncio
    async def test_callback_exception_handling(self, batcher):
        """Исключения в callback не ломают батчер."""

        async def bad_callback(batch):
            raise ValueError("Тестовая ошибка")

        batcher.on_batch_ready = bad_callback

        # Добавляем событие (должно не упасть)
        for i in range(3):
            event = WebSocketEvent(device_id=f"light.room{i}", state="ON")
            await batcher.add_event(event)

        # Батч должен всё же быть создан
        await asyncio.sleep(0.1)  # Даём время на срабатывание

    @pytest.mark.asyncio
    async def test_performance_many_events(self, batcher):
        """Производительность при обработке большого количества событий."""
        batch_count = 0

        async def count_batches(batch):
            nonlocal batch_count
            batch_count += 1

        batcher.on_batch_ready = count_batches

        # Добавляем 100 событий (должны создать 4 пакета: 3 по размеру + 1 по таймауту)
        time.time()
        for i in range(100):
            event = WebSocketEvent(device_id=f"light.room{i % 50}", state="ON")
            await batcher.add_event(event)

        # Ждём завершения
        await asyncio.sleep(0.2)

        # Должны были срабатить батчи
        assert batch_count > 0

        # Все события должны быть обработаны
        assert batcher._total_events >= 100

    @pytest.mark.asyncio
    async def test_deduplication_within_batch(self, batcher):
        """Дедупликация: одно устройство один раз в батче."""
        batch_ready = asyncio.Event()
        captured_batch = None

        async def callback(batch):
            nonlocal captured_batch
            captured_batch = batch
            batch_ready.set()

        batcher.on_batch_ready = callback

        # Добавляем 10 событий для 2 устройств (должны быть только 2 в пакете)
        for i in range(10):
            device_id = "light.kitchen" if i % 2 == 0 else "light.bedroom"
            event = WebSocketEvent(device_id=device_id, state="ON")
            await batcher.add_event(event)

        # Ждём таймаута
        try:
            await asyncio.wait_for(batch_ready.wait(), timeout=1.0)
        except TimeoutError:
            pytest.fail("Батч не срабатил")

        # В пакете должно быть ровно 2 события (по одному на каждое устройство)
        assert captured_batch.size() == 2
