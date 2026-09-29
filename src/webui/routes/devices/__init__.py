"""
REST API маршруты для управления устройствами.

Включает операции синхронизации, конфигурирования, управления командами и синхронизацией состояния.
"""

from . import access_control, devices, sources, websocket


__all__ = ["access_control", "devices", "sources", "websocket"]
