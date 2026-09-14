"""
Base Adapter - Абстрактный базовый класс для адаптеров
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable


class BaseAdapter(ABC):
    """
    Абстрактный адаптер для интеграции с внешним миром
    
    Определяет интерфейс для получения состояний устройств,
    отправки команд и подписки на изменения.
    
    Usage:
        class MyAdapter(BaseAdapter):
            def get_state(self, entity_id): ...
            def send_command(self, entity_id, command): ...
            def subscribe_to_changes(self, entity_id, callback): ...
    """
    
    @abstractmethod
    def get_state(self, entity_id: str) -> str | None:
        """
        Получить состояние устройства
        
        Args:
            entity_id: ID устройства (например, "light.living_room")
        
        Returns:
            Состояние устройства или None если не найдено
        """
        pass
    
    @abstractmethod
    def send_command(
        self, 
        entity_id: str, 
        command: str, 
        attributes: dict = None
    ) -> bool:
        """
        Отправить команду устройству
        
        Args:
            entity_id: ID устройства
            command: Команда (например, "turn_on", "set_brightness")
            attributes: Дополнительные атрибуты
        
        Returns:
            True если команда успешно отправлена
        """
        pass
    
    @abstractmethod
    def subscribe_to_changes(
        self, 
        entity_id: str, 
        callback: Callable[[str, str], None]
    ) -> None:
        """
        Подписаться на изменения состояния устройства
        
        Args:
            entity_id: ID устройства
            callback: Функция обратного вызова (entity_id, new_state)
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Проверить доступность адаптера
        
        Returns:
            True если адаптер готов к работе
        """
        pass
