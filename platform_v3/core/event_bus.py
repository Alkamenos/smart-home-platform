"""
Event Bus - Шина событий для связи компонентов через паттерн pub/sub

Типы событий:
- fsm.transition - переход автомата
- device.state_changed - изменение состояния устройства
- device.command - команда устройству
- platform.started/stopped - системные события
"""

from __future__ import annotations
from typing import Callable
from collections import defaultdict


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
        """Опубликовать событие"""
        data = data or {}
        
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                # Передаём только data (хендлер и так знает тип события)
                handler(data)
            except Exception as e:
                # Логируем ошибку, но не прерываем обработку других хендлеров
                print(f"[EventBus] Error in handler for {event_type}: {e}")
    
    def clear(self) -> None:
        """Очистить все подписки"""
        self._subscribers.clear()
    
    def get_subscribers_count(self, event_type: str) -> int:
        """Получить количество подписчиков на событие"""
        return len(self._subscribers.get(event_type, []))
