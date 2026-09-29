# Оставшиеся ошибки mypy

Дата: 2026-09-29

## Проблема

В файле `src/services/device_service.py` есть 4 ошибки mypy, которые требуют более глубокого рефакторинга:

### Ошибки

1. **Строка 438** - `src/services/device_service.py:438: error: Value of type "Coroutine[Any, Any, None]" must be used [unused-coroutine]`
   - Метод: `_publish_config_changed_event()`
   - Проблема: Вызывает `self.event_bus.publish(event)` без `await`
   - Причина: `publish()` - асинхронная функция, но вызывается в синхронном контексте

2. **Строка 475** - `src/services/device_service.py:475: error: Value of type "Coroutine[Any, Any, None]" must be used [unused-coroutine]`
   - Метод: `_publish_access_changed_event()`
   - Проблема: Вызывает `self.event_bus.publish(event)` без `await`

3. **Строка 986** - `src/services/device_service.py:986: error: Value of type "Coroutine[Any, Any, None]" must be used [unused-coroutine]`
   - Метод: `_publish_device_loaded_event()`
   - Проблема: Вызывает `self.event_bus.publish(event)` без `await`

4. **Строка 1015** - `src/services/device_service.py:1015: error: Value of type "Coroutine[Any, Any, None]" must be used [unused-coroutine]`
   - Метод: `_publish_state_changed_event()`
   - Проблема: Вызывает `self.event_bus.publish(event)` без `await`

## Корневая причина

Методы `_publish_*_event()` синхронные (`def`, не `async def`), но пытаются вызвать асинхронный метод `EventBus.publish()` без `await`.

## Решение

Нужно выбрать один из вариантов:

### Вариант 1: Сделать методы асинхронными (рекомендуется)
Изменить сигнатуру методов на `async def`:
```python
async def _publish_config_changed_event(self, ...):
    event = DeviceConfigChangedEvent(...)
    await self.event_bus.publish("device.config_changed", event)
```

Затем обновить все вызовы на `await self._publish_config_changed_event(...)`.

### Вариант 2: Удалить вызовы publish()
Закомментировать или удалить вызовы, так как события не публикуются.

### Вариант 3: Использовать синхронный способ публикации
Убедиться, что `EventBus` имеет синхронный метод публикации или создать один.

## Статус

**Не исправлено** - требует рефакторинга в другой задаче.

Все остальные lint ошибки (47 ошибок) исправлены успешно. Эти 4 ошибки mypy требуют архитектурного решения о способе публикации событий.
