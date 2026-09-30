"""
FastAPI dependencies для маршрутов устройств.

Единая точка получения доменных сервисов из app.state (research R1):
маршруты не собирают сервисы сами — это делает create_app.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import logging

from fastapi import HTTPException, Request, status

from src.core.models.device_sync_event import DeviceSyncEvent, SyncAction
from src.core.persistence.devices import DeviceSyncEventPersistence
from src.services.device_service import DeviceService


logger = logging.getLogger(__name__)


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


def get_sync_history(request: Request) -> DeviceSyncEventPersistence | None:
    """Возвращает персистентность истории операций устройства (research R3).

    История — не критичный ресурс (FR-009): при недоступном persistence
    возвращается None, вызывающий код пропускает запись/отдаёт пустой
    список вместо отказа в обслуживании.

    Args:
        request: HTTP запрос

    Returns:
        DeviceSyncEventPersistence или None, если persistence не инициализирован.
    """
    persistence = getattr(request.app.state, "persistence", None)
    if persistence is None:
        return None
    return getattr(persistence, "device_sync_events", None)


async def record_sync_event(
    request: Request,
    device_id,
    action: SyncAction,
    *,
    before: dict | None = None,
    after: dict | None = None,
    data: dict | None = None,
) -> None:
    """Записывает операцию в историю устройств (spec 005, ТР-010, FR-001).

    Общий helper для роутов устройств (research R2). Инициатор берётся из
    идентификации запроса. Ошибка записи логируется и НЕ прерывает основную
    операцию (FR-009).

    Args:
        request: HTTP запрос (идентификация из middleware)
        device_id: Устройство, над которым выполнена операция
        action: Тип операции
        before: Состояние до (config-поля, роль); для команд — None
        after: Состояние после
        data: Релевантные данные операции (команда, роль, участники)
    """
    history = get_sync_history(request)
    if history is None:
        logger.warning(
            f"История операций недоступна: {action} для устройства {device_id} не записана"
        )
        return

    user_id = (
        getattr(request.state, "user_id", None) or request.headers.get("X-User-ID") or "system"
    )
    event = DeviceSyncEvent(
        device_id=device_id,
        action=action,
        user_id=user_id,
        before=before,
        after=after,
        data=data,
    )
    try:
        await history.append_event(event)
    except Exception as e:
        logger.error(f"Ошибка записи истории ({action}, device {device_id}): {e}")
