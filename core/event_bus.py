"""
Event Bus - Шина событий для связи компонентов через паттерн pub/sub

Типы событий:
- fsm.transition - переход автомата
- device.state_changed - изменение состояния устройства
- device.command - команда устройству
- platform.started/stopped - системные события

Supports both sync and async handlers.
"""

from __future__ import annotations
from typing import Callable
from collections import defaultdict
import inspect
import asyncio


class EventBus:
    """
    Шина событий (pub/sub)
    
    Usage:
        bus = EventBus()
        bus.subscribe("fsm.transition", handler)
        bus.publish("fsm.transition", {"entity_id": "light.living_room"})
    """
    
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._logger = None  # Optional logger for error reporting
    
    def set_logger(self, logger) -> None:
        """Set logger for error reporting"""
        self._logger = logger
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Подписаться на события"""
        self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """Отписаться от событий"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False
    
    def publish(self, event_type: str, data: dict = None) -> None:
        """
        Опубликовать событие
        
        Поддерживает как синхронные, так и асинхронные хендлеры.
        Async хендлеры планируются в event loop без блокировки.
        """
        data = data or {}
        
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                result = handler(data)
                # Если хендлер вернул корутину - это async функция
                if inspect.iscoroutine(result):
                    try:
                        # Есть активный event loop - планируем задачу
                        loop = asyncio.get_running_loop()
                        loop.create_task(result)
                    except RuntimeError:
                        # Нет активного loop (синхронный контекст, тесты)
                        # Логируем предупреждение но не ломаем выполнение
                        if self._logger:
                            self._logger.warning(
                                f"Async handler for {event_type} called in sync context",
                                event_type=event_type,
                                handler=handler.__name__ if hasattr(handler, '__name__') else str(handler)
                            )
                        # В синхронном контексте async хендлер не выполнится
                        # Это ожидаемое поведение для тестов
            except Exception as e:
                # Логируем ошибку, но не прерываем обработку других хендлеров
                error_msg = f"[EventBus] Error in handler for {event_type}: {e}"
                if self._logger:
                    self._logger.error(
                        error_msg,
                        event_type=event_type,
                        handler=handler.__name__ if hasattr(handler, '__name__') else str(handler),
                        error=str(e)
                    )
                else:
                    print(error_msg)
    
    async def publish_async(self, event_type: str, data: dict = None) -> None:
        """
        Асинхронная версия publish - ждёт выполнения всех async хендлеров
        
        Используйте когда нужно гарантировать что все обработчики выполнились
        перед продолжением выполнения.
        """
        data = data or {}
        
        handlers = self._subscribers.get(event_type, [])
        tasks = []
        
        for handler in handlers:
            try:
                result = handler(data)
                if inspect.iscoroutine(result):
                    tasks.append(asyncio.create_task(result))
            except Exception as e:
                error_msg = f"[EventBus] Error in handler for {event_type}: {e}"
                if self._logger:
                    self._logger.error(error_msg, event_type=event_type, error=str(e))
                else:
                    print(error_msg)
        
        # Ждём выполнения всех async хендлеров
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def clear(self) -> None:
        """Очистить все подписки"""
        self._subscribers.clear()
    
    def get_subscribers_count(self, event_type: str) -> int:
        """Получить количество подписчиков на событие"""
        return len(self._subscribers.get(event_type, []))
