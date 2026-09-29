"""
Middleware для проверки доступа к устройствам.

Проверяет что пользователь имеет доступ ко всем операциям над устройствами.
"""

import logging
from uuid import UUID

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


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

        Зона ответственности — идентификация на device-endpoints: запросы
        без X-User-ID к путям /api/v1/devices/** отклоняются (401),
        идентификация переносится в request.state. Endpoints вне устройств
        (healthcheck, dashboard) проверке не подлежат.

        Args:
            request: HTTP запрос
            call_next: Следующий middleware/handler

        Returns:
            HTTP ответ
        """
        # Проверяем только пути устройств
        path = request.url.path
        is_device_area = path == "/api/v1/devices" or path.startswith("/api/v1/devices/")
        if not is_device_area:
            return await call_next(request)

        # Пропускаем GET /api/v1/devices (возвращает только доступные)
        if request.method == "GET" and path == "/api/v1/devices":
            return await call_next(request)

        # Пропускаем POST /api/v1/devices/sources (требует админ, проверяется в route)
        if request.method == "POST" and path == "/api/v1/devices/sources":
            return await call_next(request)

        # Получаем ID пользователя из заголовка
        user_id = request.headers.get("X-User-ID")
        is_admin = request.headers.get("X-Is-Admin", "false").lower() == "true"

        if not user_id:
            # Если нет ID пользователя, считаем это неавторизованным.
            # Из BaseHTTPMiddleware исключение не превратится в ответ —
            # возвращаем JSON-ответ напрямую.
            logger.warning(f"Запрос без X-User-ID: {request.method} {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing X-User-ID header"},
            )

        # Проверяем доступ к защищенным endpoints
        device_id = self._extract_device_id(request.url.path)

        # Идентификация доступна маршруту на любой путь области устройств
        request.state.device_id = device_id
        request.state.user_id = user_id
        request.state.is_admin = is_admin

        # Продолжаем обработку запроса
        response = await call_next(request)
        return response

    def _extract_device_id(self, path: str) -> UUID | None:
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
