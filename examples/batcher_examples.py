"""
Пример использования WebSocketEventBatcher для синхронизации состояния.

Демонстрирует:
1. Создание и конфигурацию батчера
2. Добавление событий
3. Обработку готовых пакетов
4. Получение статистики
5. Интеграцию с WebSocket клиентом Home Assistant
"""

import asyncio
import logging
from typing import Any

from core import WebSocketBatch, WebSocketEvent, WebSocketEventBatcher


# Настройка логирования
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================
# Пример 1: Прямое использование батчера
# ============================================


async def example_direct_batcher():
    """Пример прямого использования батчера."""
    logger.info("=" * 60)
    logger.info("ПРИМЕР 1: Прямое использование батчера")
    logger.info("=" * 60)

    # Подсчит обработанных пакетов
    processed_batches = 0

    async def handle_batch(batch: WebSocketBatch) -> None:
        """Callback для обработки готовых пакетов."""
        nonlocal processed_batches
        processed_batches += 1
        events = batch.get_events_list()

        logger.info(f"\nПакет #{batch.batch_id} готов!")
        logger.info(f"Размер: {batch.size()} событий")

        for event in events:
            logger.info(
                f"  - {event.device_id}: {event.state} "
                f"(яркость: {event.attributes.get('brightness', 'N/A')})"
            )

    # Создание батчера
    batcher = WebSocketEventBatcher(
        batch_timeout_ms=100,  # 100ms таймаут
        batch_size_limit=5,  # максимум 5 устройств
        on_batch_ready=handle_batch,
    )

    logger.info("Батчер создан: timeout=100ms, size_limit=5")

    # Запуск батчера
    await batcher.start()

    # Добавляем события
    logger.info("\nДобавляем события...")
    for i in range(12):
        device_id = f"light.room{i % 3}"
        state = "ON" if i % 2 == 0 else "OFF"
        brightness = (i * 10) % 256

        event = WebSocketEvent(
            device_id=device_id, state=state, attributes={"brightness": brightness}
        )

        await batcher.add_event(event)
        logger.info(f"Событие {i + 1}: {device_id} = {state}")

        # Имитируем небольшую задержку между событиями
        await asyncio.sleep(0.01)

    # Даем время на срабатывание батчей
    await asyncio.sleep(0.3)

    # Остановка батчера
    await batcher.stop()

    # Статистика
    stats = batcher.get_statistics()
    logger.info("\nСтатистика батчера:")
    logger.info(f"  Всего событий: {stats['total_events']}")
    logger.info(f"  Создано пакетов: {stats['total_batches']}")
    logger.info(f"  Среднее событий/пакет: {stats['avg_events_per_batch']:.1f}")


# ============================================
# Пример 2: Использование через WebSocket клиент
# ============================================


async def example_websocket_client():
    """Пример использования батчера через WebSocket клиент."""
    logger.info("\n" + "=" * 60)
    logger.info("ПРИМЕР 2: Интеграция с WebSocket клиентом")
    logger.info("=" * 60)

    # Обработчик событий
    def handle_events(data: dict[str, Any]) -> None:
        """Обработчик событий состояния."""
        if isinstance(data, dict) and "batch_id" in data:
            # Это пакет от батчера
            logger.info(f"\nОбработан пакет #{data['batch_id']}:")
            for event in data.get("events", []):
                logger.info(f"  - {event['device_id']}: {event['state']}")
        else:
            # Это одиночное событие
            logger.info(f"Событие: {data}")

    # Создание WebSocket клиента с батчингом
    from adapters.home_assistant.websocket_client import HAWebSocketClient

    _ = HAWebSocketClient(
        base_url="http://homeassistant.local:8123",
        token="your_token_here",
        on_state_changed=handle_events,
        batch_timeout_ms=100,  # 100ms таймаут батча
        batch_size_limit=10,  # максимум 10 событий в пакете
        enable_batching=True,  # включить батчинг
    )

    logger.info("WebSocket клиент создан с батчингом")
    logger.info("Параметры батчера:")
    logger.info("  - batch_timeout_ms: 100")
    logger.info("  - batch_size_limit: 10")

    # В реальном приложении:
    # await client.connect()
    # await client.subscribe_to_state_changes()
    # await client.listen()  # Блокирующий вызов

    # Получение статистики (после работы)
    # stats = client.get_batch_statistics()
    # logger.info(f"Статистика: {stats}")


# ============================================
# Пример 3: Сценарий частых обновлений
# ============================================


async def example_high_frequency():
    """Пример обработки большого количества частых событий."""
    logger.info("\n" + "=" * 60)
    logger.info("ПРИМЕР 3: Сценарий частых обновлений (100 событий/сек)")
    logger.info("=" * 60)

    processed_count = 0
    start_time = None

    async def batch_processor(batch: WebSocketBatch) -> None:
        nonlocal processed_count
        processed_count += batch.size()

    batcher = WebSocketEventBatcher(
        batch_timeout_ms=100, batch_size_limit=20, on_batch_ready=batch_processor
    )

    await batcher.start()
    start_time = asyncio.get_event_loop().time()

    # Генерируем 100 событий в быстрой последовательности
    logger.info("Добавляем 100 событий...")
    for i in range(100):
        event = WebSocketEvent(
            device_id=f"sensor.temp_{i % 10}", state=str(20 + i % 10), attributes={"unit": "C"}
        )
        await batcher.add_event(event)

    # Ждем завершения батчинга
    await asyncio.sleep(0.5)
    await batcher.stop()

    elapsed = asyncio.get_event_loop().time() - start_time
    stats = batcher.get_statistics()

    logger.info("\nРезультаты:")
    logger.info("  Добавлено событий: 100")
    logger.info(f"  Обработано устройств: {processed_count}")
    logger.info(f"  Создано пакетов: {stats['total_batches']}")
    logger.info(f"  Время обработки: {elapsed:.3f}сек")
    logger.info(f"  Производительность: {processed_count / elapsed:.0f} событий/сек")

    # Сравнение: без батчинга это заняло бы 100 обработок
    # С батчингом: ~5-6 обработок
    speedup = 100 / stats["total_batches"]
    logger.info(f"  Ускорение: {speedup:.1f}x")


# ============================================
# Пример 4: Обработка ошибок и recovery
# ============================================


async def example_error_handling():
    """Пример обработки ошибок в батчере."""
    logger.info("\n" + "=" * 60)
    logger.info("ПРИМЕР 4: Обработка ошибок")
    logger.info("=" * 60)

    error_count = 0

    async def risky_handler(batch: WebSocketBatch) -> None:
        """Обработчик который может выкинуть ошибку."""
        nonlocal error_count
        # Иногда вызываем ошибку
        if batch.batch_id % 2 == 0:
            error_count += 1
            raise ValueError(f"Случайная ошибка в пакете {batch.batch_id}")
        logger.info(f"Успешно обработан пакет {batch.batch_id}")

    batcher = WebSocketEventBatcher(
        batch_timeout_ms=50, batch_size_limit=3, on_batch_ready=risky_handler
    )

    await batcher.start()

    # Добавляем события - некоторые батчи будут ошибаться
    for i in range(9):
        event = WebSocketEvent(device_id=f"device_{i}", state="OK")
        await batcher.add_event(event)

    await asyncio.sleep(0.2)
    await batcher.stop()

    stats = batcher.get_statistics()
    logger.info("\nРезультаты:")
    logger.info(f"  Всего батчей: {stats['total_batches']}")
    logger.info(f"  Ошибок: {error_count}")
    logger.info("  Батчер продолжил работу: ✓")


# ============================================
# Главная функция
# ============================================


async def main():
    """Запуск всех примеров."""
    try:
        await example_direct_batcher()
        await example_websocket_client()
        await example_high_frequency()
        await example_error_handling()

        logger.info("\n" + "=" * 60)
        logger.info("ВСЕ ПРИМЕРЫ ЗАВЕРШЕНЫ")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
