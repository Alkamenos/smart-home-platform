"""
Модуль персистентности для smart-home-platform.

Включает:
- Кэширование устройств (DeviceCache)
- Индексирование устройств (IndexManager)
- Сохранение и загрузку состояния
- Управление источниками данных
- WebSocket batch обработка
"""

from core.persistence.cache import DeviceCache
from core.persistence.index_manager import IndexManager


__all__ = [
    "DeviceCache",
    "IndexManager",
]
