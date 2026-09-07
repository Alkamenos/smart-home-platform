"""
Mock Adapter - Мок-адаптер для локального тестирования без Home Assistant

Возможности:
- Хранит состояния устройств в памяти
- Позволяет устанавливать состояния вручную (для тестов)
- Логирует все вызовы команд
- Эмулирует задержки и ошибки
"""

from __future__ import annotations
import time
from typing import Callable
from .base import BaseAdapter


class MockAdapter(BaseAdapter):
    """
    Мок-адаптер для тестирования
    
    Usage:
        adapter = MockAdapter()
        adapter.set_state("light.living_room", "on")
        state = adapter.get_state("light.living_room")  # "on"
        commands = adapter.get_commands_log()  # История команд
    """
    
    def __init__(self, emulate_delay: bool = False):
        self._states: dict[str, str] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._commands_log: list[dict] = []
        self._emulate_delay = emulate_delay
        self._available = True
    
    def get_state(self, entity_id: str) -> str | None:
        """Получить состояние устройства"""
        return self._states.get(entity_id)
    
    def set_state(self, entity_id: str, state: str) -> None:
        """
        Установить состояние (для тестов)
        
        Args:
            entity_id: ID устройства
            state: Новое состояние
        """
        old_state = self._states.get(entity_id)
        self._states[entity_id] = state
        
        # Уведомляем подписчиков
        if entity_id in self._callbacks:
            for callback in self._callbacks[entity_id]:
                try:
                    callback(entity_id, state)
                except Exception:
                    pass
        
        # Логируем изменение
        self._commands_log.append({
            "timestamp": time.time(),
            "type": "state_change",
            "entity_id": entity_id,
            "old_state": old_state,
            "new_state": state
        })
    
    def send_command(
        self, 
        entity_id: str, 
        command: str, 
        attributes: dict = None
    ) -> bool:
        """Отправить команду устройству"""
        if not self._available:
            return False
        
        if self._emulate_delay:
            time.sleep(0.01)  # Эмуляция задержки сети
        
        # Логируем команду
        self._commands_log.append({
            "timestamp": time.time(),
            "type": "command",
            "entity_id": entity_id,
            "command": command,
            "attributes": attributes or {}
        })
        
        # Для мока просто считаем команду успешной
        return True
    
    def subscribe_to_changes(
        self, 
        entity_id: str, 
        callback: Callable[[str, str], None]
    ) -> None:
        """Подписаться на изменения состояния устройства"""
        if entity_id not in self._callbacks:
            self._callbacks[entity_id] = []
        self._callbacks[entity_id].append(callback)
    
    def is_available(self) -> bool:
        """Проверить доступность адаптера"""
        return self._available
    
    def set_available(self, available: bool) -> None:
        """Установить доступность (для тестов)"""
        self._available = available
    
    def get_commands_log(self) -> list[dict]:
        """Получить лог команд (для проверок в тестах)"""
        return list(self._commands_log)
    
    def clear_commands_log(self) -> None:
        """Очистить лог команд"""
        self._commands_log.clear()
    
    def reset(self) -> None:
        """Сбросить все состояния и логи"""
        self._states.clear()
        self._callbacks.clear()
        self._commands_log.clear()
        self._available = True
