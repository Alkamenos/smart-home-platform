"""
FastAPI dependencies для маршрутов устройств.

Единая точка получения доменных сервисов из app.state (research R1):
маршруты не собирают сервисы сами — это делает create_app.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from fastapi import HTTPException, Request, status

from src.services.device_service import DeviceService


def get_device_service(request: Request) -> DeviceService:
    """Возвращает DeviceService приложения (app.state, создан в create_app).

    Args:
        request: HTTP запрос (или запрос WS-handshake — web.state прокидывается)

    Returns:
        DeviceService, инициализированный в create_app.

    Raises:
        HTTPException: 503 если сервис недоступен.
    """
    service = getattr(request.app.state, "device_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device service is not available",
        )
    return service
