"""
API routes для управления доступом к устройствам.

Endpoints для назначения, обновления и отзыва доступа пользователей к устройствам.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.services.device_service import DeviceService
from src.webui.routes.devices.deps import get_device_service


logger = logging.getLogger(__name__)

# Инициализируем router
router = APIRouter(prefix="/api/v1/devices", tags=["access-control"])


# Dependency для получения текущего пользователя
def get_current_user(x_user_id: str | None = Header(None)) -> str:
    """Получает ID текущего пользователя из заголовка.

    Args:
        x_user_id: ID пользователя из заголовка X-User-ID

    Returns:
        ID пользователя

    Raises:
        HTTPException: Если пользователь не авторизован
    """
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-User-ID header"
        )
    return x_user_id


def get_is_admin(x_is_admin: str | None = Header(None)) -> bool:
    """Проверяет является ли пользователь администратором.

    Args:
        x_is_admin: Флаг администратора из заголовка X-Is-Admin

    Returns:
        True если администратор
    """
    return (x_is_admin or "").lower() == "true"


def require_admin(is_admin: bool = Depends(get_is_admin)):
    """Dependency для проверки что пользователь администратор.

    Args:
        is_admin: Результат проверки из get_is_admin

    Raises:
        HTTPException: Если пользователь не администратор
    """
    if not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return is_admin


# T068: Routes для управления доступом


class GrantAccessRequest(BaseModel):
    """Запрос на назначение доступа (contracts §3)."""

    user_id: str = Field(min_length=1, description="ID пользователя")
    role: str = Field(description="Роль доступа: viewer, controller, admin")


_VALID_ROLES = ("viewer", "controller", "admin")


@router.post("/{device_id}/access", status_code=201)
async def grant_device_access(
    device_id: UUID,
    request: GrantAccessRequest,
    current_user: str = Depends(get_current_user),
    is_admin: bool = Depends(require_admin),
    service: DeviceService = Depends(get_device_service),
):
    """Предоставляет пользователю доступ к устройству.

    Только администраторы могут предоставлять доступ.

    Args:
        device_id: ID устройства
        request: Данные доступа (user_id, role)
        current_user: Текущий пользователь (администратор)
        is_admin: Проверка что это администратор
        service: DeviceService приложения (dependency)

    Returns:
        Созданная запись доступа

    Raises:
        HTTPException: 404 если устройство не найдено, 400 при валидации, 403 без прав
    """
    if request.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {request.role}. Must be one of: viewer, controller, admin",
        )
    try:
        access = await service.grant_access(
            device_id=device_id,
            user_id=request.user_id,
            role=request.role,
            granted_by=current_user,
        )

        if not access:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found",
            )

        return {
            "id": str(access.id),
            "device_id": str(access.device_id),
            "user_id": access.user_id,
            "role": access.role,
            "granted_by": access.granted_by,
            "created_at": access.created_at.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка предоставления доступа: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to grant access"
        ) from e


@router.delete("/{device_id}/access/{access_id}", status_code=204)
async def revoke_device_access(
    device_id: UUID,
    access_id: UUID,
    current_user: str = Depends(get_current_user),
    is_admin: bool = Depends(require_admin),
    service: DeviceService = Depends(get_device_service),
):
    """Отзывает доступ пользователя к устройству.

    Только администраторы могут отзывать доступ.

    Args:
        device_id: ID устройства
        access_id: ID записи доступа для удаления
        current_user: Текущий пользователь (администратор)
        is_admin: Проверка что это администратор
        service: DeviceService приложения (dependency)

    Raises:
        HTTPException: 404 если запись не существует или относится к другому устройству
    """
    try:
        # Запись должна существовать и относиться к этому устройству
        accesses = await service.get_device_accesses(device_id)
        record_exists = any(str(access.id) == str(access_id) for access in accesses)
        if not record_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Access record not found",
            )

        result = await service.revoke_access(access_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Access record not found",
            )
        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка отзыва доступа: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to revoke access"
        ) from e


@router.get("/{device_id}/access", status_code=200)
async def get_device_access_list(
    device_id: UUID,
    current_user: str = Depends(get_current_user),
    is_admin: bool = Depends(require_admin),
    service: DeviceService = Depends(get_device_service),
):
    """Получает список всех доступов к устройству.

    Только администраторы могут просматривать список доступа.

    Args:
        device_id: ID устройства
        current_user: Текущий пользователь (администратор)
        is_admin: Проверка что это администратор
        service: DeviceService приложения (dependency)

    Returns:
        Список записей доступа

    Raises:
        HTTPException: 404 если устройство не найдено
    """
    try:
        accesses = await service.get_device_accesses(device_id)

        return [
            {
                "id": str(access.id),
                "device_id": str(access.device_id),
                "user_id": access.user_id,
                "role": access.role,
                "granted_by": access.granted_by,
                "created_at": access.created_at.isoformat(),
            }
            for access in accesses
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения доступов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get access list"
        ) from e
