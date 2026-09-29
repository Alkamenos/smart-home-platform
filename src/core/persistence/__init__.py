"""
Модуль персистентности для smart-home-platform.

Включает:
- Кэширование устройств (DeviceCache)
- Индексирование устройств (IndexManager)
- Сохранение и загрузку состояния
- Управление источниками данных
- WebSocket batch обработка
"""

from src.core.persistence.cache import DeviceCache
from src.core.persistence.index_manager import IndexManager

__all__ = [
    "DeviceCache",
    "IndexManager",
]
