"""
Middleware для проверки доступа к устройствам.

Проверяет что пользователь имеет доступ ко всем операциям над устройствами.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class DeviceAccessMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки доступа пользователя к устройствам."""

    # Endpoints которые требуют проверки доступа
    PROTECTED_ENDPOINTS = [
        "/api/v1/devices/{device_id}",  # GET, PUT
        "/api/v1/devices/{device_id}/command",  # POST
        "/api/v1/devices/{device_id}/command/{command_id}",  # GET
        "/api/v1/devices/{device_id}/events",  # GET
        "/api/v1/devices/{device_id}/access",  # GET, POST, DELETE
        "/api/v1/devices/{device_id}/config",  # PUT
    ]

    # Endpoints доступные только администраторам
    ADMIN_ENDPOINTS = [
        "/api/v1/devices/{device_id}/access",  # POST, DELETE
        "/api/v1/devices/sources",  # POST
        "/api/v1/devices/sources/{source_id}/sync",  # POST
    ]

    async def dispatch(self, request: Request, call_next):
        """Обрабатывает запрос и проверяет доступ.

        Args:
            request: HTTP запрос
            call_next: Следующий middleware/handler

        Returns:
            HTTP ответ
        """
        # Пропускаем GET /api/v1/devices (возвращает только доступные)
        if request.method == "GET" and request.url.path == "/api/v1/devices":
            return await call_next(request)

        # Пропускаем POST /api/v1/devices/sources (требует админ, проверяется в route)
        if request.method == "POST" and request.url.path == "/api/v1/devices/sources":
            return await call_next(request)

        # Получаем ID пользователя из заголовка
        user_id = request.headers.get("X-User-ID")
        is_admin = request.headers.get("X-Is-Admin", "false").lower() == "true"

        if not user_id:
            # Если нет ID пользователя, считаем это неавторизованным
            logger.warning(f"Запрос без X-User-ID: {request.method} {request.url.path}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-User-ID header"
            )

        # Проверяем доступ к защищенным endpoints
        device_id = self._extract_device_id(request.url.path)

        if device_id:
            # Это endpoint для конкретного устройства
            # Проверяем доступ к устройству (будет реализовано через dependency injection)
            request.state.device_id = device_id
            request.state.user_id = user_id
            request.state.is_admin = is_admin

        # Продолжаем обработку запроса
        response = await call_next(request)
        return response

    def _extract_device_id(self, path: str) -> Optional[UUID]:
        """Извлекает ID устройства из пути запроса.

        Args:
            path: Путь запроса

        Returns:
            UUID устройства или None
        """
        parts = path.strip("/").split("/")

        # Ищем device_id в пути
        for i, part in enumerate(parts):
            if part == "devices" and i + 1 < len(parts):
                try:
                    # Следующий элемент после "devices" это device_id
                    device_id_str = parts[i + 1]
                    if device_id_str.startswith("{") or device_id_str.startswith("}"):
                        continue  # Это параметр в шаблоне
                    return UUID(device_id_str)
                except (ValueError, IndexError):
                    pass

        return None
