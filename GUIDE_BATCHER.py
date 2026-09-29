"""
GUIDE: Использование WebSocket Event Batcher

Краткое руководство по использованию батчера для синхронизации состояния
WebSocket событий в smart-home-platform.
"""

# ============================================================================
# 1. УСТАНОВКА И ИМПОРТ
# ============================================================================

# Батчер доступен из core модуля:
from core import WebSocketEventBatcher, WebSocketEvent, WebSocketBatch

# Или прямой импорт:
from core.persistence.websocket_batcher import WebSocketEventBatcher


# ============================================================================
# 2. ИСПОЛЬЗОВАНИЕ С WebSocket КЛИЕНТОМ (РЕКОМЕНДУЕТСЯ)
# ============================================================================

# Батчер автоматически используется в HAWebSocketClient

from adapters.home_assistant.websocket_client import HAWebSocketClient

# Создаём клиент с батчингом (по умолчанию включен)
client = HAWebSocketClient(
    base_url="http://homeassistant.local:8123",
    token="your_long_lived_token",
    on_state_changed=handle_state_changes,  # callback для готовых пакетов
    batch_timeout_ms=100,                    # 100ms таймаут
    batch_size_limit=10,                     # 10 устройств в пакете
    enable_batching=True                     # включить батчинг
)

# Использование:
await client.connect()
await client.subscribe_to_state_changes()
await client.listen()  # listen() использует батчер автоматически


# ============================================================================
# 3. ИСПОЛЬЗОВАНИЕ БАТЧЕРА НАПРЯМУЮ
# ============================================================================

import asyncio

# 3.1 Создание батчера
batcher = WebSocketEventBatcher(
    batch_timeout_ms=100,      # Таймаут для накопления
    batch_size_limit=10,       # Максимум событий в пакете
    on_batch_ready=process_batch,  # Callback при готовности
    logger_instance=logger     # Logger для отладки
)

# 3.2 Обработчик для готовых пакетов
async def process_batch(batch: WebSocketBatch):
    """Обработать готовый пакет событий."""
    print(f"Пакет {batch.batch_id}: {batch.size()} событий")

    for event in batch.get_events_list():
        print(f"  - {event.device_id}: {event.state}")
        print(f"    Атрибуты: {event.attributes}")

# 3.3 Запуск батчера
await batcher.start()

# 3.4 Добавление событий
event = WebSocketEvent(
    device_id="light.kitchen",
    state="ON",
    attributes={"brightness": 100, "color_temp": 5000}
)
await batcher.add_event(event)

# 3.5 Получение статистики
stats = batcher.get_statistics()
print(f"Всего событий: {stats['total_events']}")
print(f"Создано пакетов: {stats['total_batches']}")
print(f"Текущий размер буфера: {stats['current_buffer_size']}")

# 3.6 Остановка батчера
await batcher.stop()  # Обработает оставшиеся события


# ============================================================================
# 4. ПАРАМЕТРЫ БАТЧЕРА
# ============================================================================

# batch_timeout_ms (по умолчанию 100)
# ────────────────
# Таймаут в миллисекундах для накопления событий.
# При достижении таймаута батч срабатит автоматически.
#
# Примеры:
#   50ms   - быстрая обработка, но больше батчей
#   100ms  - сбалансированный вариант (по умолчанию)
#   200ms  - меньше батчей, но выше задержка

batcher_fast = WebSocketEventBatcher(batch_timeout_ms=50)
batcher_balanced = WebSocketEventBatcher(batch_timeout_ms=100)
batcher_slow = WebSocketEventBatcher(batch_timeout_ms=200)


# batch_size_limit (по умолчанию 10)
# ──────────────────
# Максимальное количество уникальных устройств в одном пакете.
# При достижении лимита батч срабатит немедленно.
#
# Примеры:
#   5    - маленькие пакеты, много батчей
#   10   - средние пакеты (по умолчанию)
#   50   - большие пакеты, меньше обработок

batcher_small = WebSocketEventBatcher(batch_size_limit=5)
batcher_medium = WebSocketEventBatcher(batch_size_limit=10)
batcher_large = WebSocketEventBatcher(batch_size_limit=50)


# ============================================================================
# 5. ОБРАБОТЧИК ГОТОВЫХ ПАКЕТОВ (CALLBACK)
# ============================================================================

# 5.1 Асинхронный callback
async def async_handler(batch: WebSocketBatch):
    """Асинхронный обработчик пакета."""
    events = batch.get_events_list()

    for event in events:
        # Например, сохраняем в БД
        await database.save_state(event.device_id, event.state)

        # Или отправляем на обновление UI
        await ws.send_json({
            "type": "state_changed",
            "device": event.device_id,
            "state": event.state
        })

# 5.2 Синхронный callback
def sync_handler(batch: WebSocketBatch):
    """Синхронный обработчик пакета."""
    for event in batch.get_events_list():
        print(f"Событие: {event.device_id} = {event.state}")

# 5.3 Использование
batcher = WebSocketEventBatcher(
    on_batch_ready=async_handler  # Может быть async или sync
)


# ============================================================================
# 6. ОТКЛЮЧЕНИЕ БАТЧИНГА
# ============================================================================

# Если нужно вернуться к исходному поведению без батчинга:

client = HAWebSocketClient(
    base_url="http://localhost:8123",
    token="token",
    enable_batching=False  # Батчинг отключен
)

# При enable_batching=False:
# - События обрабатываются немедленно
# - Callback вызывается для каждого события
# - Поведение как в оригинальной версии


# ============================================================================
# 7. ТИПИЧНЫЕ СЦЕНАРИИ
# ============================================================================

# Сценарий 1: Синхронизация с БД
# ──────────────────────────────

async def database_sync(batch: WebSocketBatch):
    """Синхронизировать пакет событий с БД."""
    events_data = []

    for event in batch.get_events_list():
        events_data.append({
            "device_id": event.device_id,
            "state": event.state,
            "attributes": event.attributes,
            "timestamp": event.timestamp
        })

    # Массовая вставка в БД
    await db.insert_many("device_states", events_data)

batcher = WebSocketEventBatcher(
    batch_timeout_ms=100,
    batch_size_limit=50,  # Больше батч для БД
    on_batch_ready=database_sync
)


# Сценарий 2: Отправка на фронтенд
# ──────────────────────────────────

async def frontend_sync(batch: WebSocketBatch):
    """Отправить обновления на фронтенд."""
    updates = []

    for event in batch.get_events_list():
        updates.append({
            "device": event.device_id,
            "state": event.state,
            "brightness": event.attributes.get("brightness")
        })

    # Отправляем всем подключенным клиентам
    for websocket in connected_clients:
        await websocket.send_json({
            "type": "state_updates",
            "updates": updates
        })

batcher = WebSocketEventBatcher(
    batch_timeout_ms=100,
    batch_size_limit=20,
    on_batch_ready=frontend_sync
)


# Сценарий 3: Обработка критичных событий
# ───────────────────────────────────────

async def smart_handler(batch: WebSocketBatch):
    """Обработать события с приоритетом."""
    critical = []
    normal = []

    for event in batch.get_events_list():
        # Критичные устройства (двери, замки, дымовые датчики)
        if event.device_id.startswith(("lock.", "alarm.", "sensor.smoke")):
            critical.append(event)
        else:
            normal.append(event)

    # Обработать критичные события первыми
    for event in critical:
        await handle_critical_event(event)

    # Потом обычные
    for event in normal:
        await handle_normal_event(event)


# ============================================================================
# 8. ОТЛАДКА И МОНИТОРИНГ
# ============================================================================

# Получение статистики батчера
stats = batcher.get_statistics()

print("Статистика батчера:")
print(f"  Всего обработано событий: {stats['total_events']}")
print(f"  Создано пакетов: {stats['total_batches']}")
print(f"  Среднее событий/пакет: {stats['avg_events_per_batch']:.1f}")
print(f"  Текущий размер буфера: {stats['current_buffer_size']}")
print(f"  Время последнего пакета: {stats['last_batch_time']}")

# Доступ к батчеру через клиент
client = HAWebSocketClient(...)
batcher = client.get_batcher()
if batcher:
    stats = client.get_batch_statistics()
    print(f"Батчер работает: {stats['total_events']} событий обработано")


# ============================================================================
# 9. ОБРАБОТКА ОШИБОК
# ============================================================================

# Батчер безопасно обрабатывает ошибки в callback

async def risky_handler(batch: WebSocketBatch):
    """Callback который может выкинуть ошибку."""
    for event in batch.get_events_list():
        try:
            # Может выкинуть исключение
            await process_event(event)
        except Exception as e:
            logger.error(f"Ошибка при обработке {event.device_id}: {e}")
            # Батчер продолжит работу

batcher = WebSocketEventBatcher(
    on_batch_ready=risky_handler
)

# Батчер перехватит исключение и залогирует его
# Работа продолжится нормально


# ============================================================================
# 10. ЛУЧШИЕ ПРАКТИКИ
# ============================================================================

# 1. Используйте батчер через WebSocket клиент (проще и безопаснее)
#    ✓ Автоматическое управление жизненным циклом
#    ✓ Интеграция с существующим кодом

# 2. Выбирайте подходящие параметры для вашего случая
#    - Высокочастотные события: batch_timeout_ms=50, batch_size_limit=20
#    - Обычное использование: batch_timeout_ms=100, batch_size_limit=10
#    - Редкие события: batch_timeout_ms=200, batch_size_limit=5

# 3. Делайте callback быстрым и асинхронным
#    ✓ Используйте async/await
#    ✗ Не блокируйте батчер долгими операциями

# 4. Обрабатывайте ошибки в callback
#    ✓ Try/except блоки
#    ✗ Не позволяйте исключениям проходить наружу

# 5. Мониторьте статистику
#    ✓ Проверяйте total_events и total_batches
#    ✗ Не игнорируйте performance metrics

# 6. Корректно завершайте работу
#    ✓ Вызывайте await batcher.stop() при shutdown
#    ✗ Не убивайте батчер резко
