"""
REST API маршруты для управления устройствами.

Включает операции синхронизации, конфигурирования, управления командами и синхронизацией состояния.
"""

from . import devices, sources, websocket


__all__ = ["devices", "sources", "websocket"]
