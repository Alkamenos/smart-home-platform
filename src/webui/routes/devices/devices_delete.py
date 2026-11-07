"""Device deletion route (spec 018, T059)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from webui.routes.devices.deps import get_device_service, get_lifecycle_service
from webui.routes.devices.devices_common import _ROLE_ADMIN, _require_access_or_403


logger = logging.getLogger(__name__)
router = APIRouter()


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(request: Request, device_id: UUID) -> Response:
    """T040: Полностью удаляет устройство (spec 006, US4).

    Каскад выполняет сервис жизненного цикла: снятие машин состояний →
    отзыв прав → удаление из хранилища, кэша и индексов → удаление из
    манифеста → перестроение маршрутизации → аудит. Повторное удаление
    считается успехом (FR-027), неизвестное устройство — 404 (FR-025).

    Args:
        request: HTTP запрос (идентификация из middleware)
        device_id: ID устройства

    Returns:
        204 без тела

    Raises:
        HTTPException: 403 без прав администратора, 404 если устройство не найдено,
            500 если сервис жизненного цикла недоступен
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)
    if not device:
        # Повторное удаление — успех (идемпотентность), неизвестный id — 404
        if device_service.was_device_deleted(device_id):
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_ADMIN)

    lifecycle_service = get_lifecycle_service(request)
    if lifecycle_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис жизненного цикла устройств недоступен",
        )

    user_id = (
        getattr(request.state, "user_id", None) or request.headers.get("X-User-ID") or "system"
    )
    try:
        await lifecycle_service.delete_device(device, user_id=user_id)
    except ValueError as e:
        logger.warning(f"Не удалось удалить устройство {device_id}: {e}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Ошибка удаления устройства {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось удалить устройство",
        ) from e

    logger.info(f"Устройство удалено через API: {device.ha_entity_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
