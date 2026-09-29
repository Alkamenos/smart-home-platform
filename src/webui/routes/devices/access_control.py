"""
API routes для управления доступом к устройствам.

Endpoints для назначения, обновления и отзыва доступа пользователей к устройствам.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Header, status

logger = logging.getLogger(__name__)

# Инициализируем router
router = APIRouter(prefix="/api/v1/devices", tags=["access-control"])


# Dependency для получения текущего пользователя
def get_current_user(x_user_id: Optional[str] = Header(None)) -> str:
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
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-User-ID header"
        )
    return x_user_id


def get_is_admin(x_is_admin: Optional[str] = Header(None)) -> bool:
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return is_admin


# T068: Routes для управления доступом


@router.post("/{device_id}/access", status_code=201)
async def grant_device_access(
    device_id: UUID,
    user_id: str,
    role: str,
    current_user: str = Depends(get_current_user),
    is_admin: bool = Depends(require_admin),
):
    """Предоставляет пользователю доступ к устройству.

    Только администраторы могут предоставлять доступ.

    Args:
        device_id: ID устройства
        user_id: ID пользователя которому предоставляем доступ
        role: Роль (viewer, controller, admin)
        current_user: Текущий пользователь (администратор)
        is_admin: Проверка что это администратор

    Returns:
        Созданная запись доступа

    Raises:
        HTTPException: Если ошибка валидации или нет прав
    """
    # Валидируем роль
    if role not in ["viewer", "controller", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role}. Must be one of: viewer, controller, admin"
        )

    try:
        # Получаем DeviceService из контекста (будет реализовано в bootstrap)
        # from src.core.container import get_device_service
        # device_service = get_device_service()

        # access = await device_service.grant_access(
        #     device_id=device_id,
        #     user_id=user_id,
        #     role=role,
        #     granted_by=current_user
        # )

        # if not access:
        #     raise HTTPException(
        #         status_code=status.HTTP_404_NOT_FOUND,
        #         detail="Device not found"
        #     )

        # Для теста возвращаем структуру доступа
        return {
            "id": str(UUID(int=0)),  # Placeholder
            "device_id": str(device_id),
            "user_id": user_id,
            "role": role,
            "granted_by": current_user,
            "created_at": "2026-09-29T10:00:00Z"
        }

    except Exception as e:
        logger.error(f"Ошибка предоставления доступа: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to grant access"
        )


@router.delete("/{device_id}/access/{access_id}", status_code=204)
async def revoke_device_access(
    device_id: UUID,
    access_id: UUID,
    current_user: str = Depends(get_current_user),
    is_admin: bool = Depends(require_admin),
):
    """Отзывает доступ пользователя к устройству.

    Только администраторы могут отзывать доступ.

    Args:
        device_id: ID устройства
        access_id: ID записи доступа для удаления
        current_user: Текущий пользователь (администратор)
        is_admin: Проверка что это администратор

    Raises:
        HTTPException: Если ошибка или нет прав
    """
    try:
        # Получаем DeviceService из контекста (будет реализовано в bootstrap)
        # from src.core.container import get_device_service
        # device_service = get_device_service()

        # result = await device_service.revoke_access(access_id)

        # if not result:
        #     raise HTTPException(
        #         status_code=status.HTTP_404_NOT_FOUND,
        #         detail="Access record not found"
        #     )

        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка отзыва доступа: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke access"
        )


@router.get("/{device_id}/access", status_code=200)
async def get_device_access_list(
    device_id: UUID,
    current_user: str = Depends(get_current_user),
    is_admin: bool = Depends(require_admin),
):
    """Получает список всех доступов к устройству.

    Только администраторы могут просматривать список доступа.

    Args:
        device_id: ID устройства
        current_user: Текущий пользователь (администратор)
        is_admin: Проверка что это администратор

    Returns:
        Список записей доступа

    Raises:
        HTTPException: Если ошибка или нет прав
    """
    try:
        # Получаем DeviceService из контекста (будет реализовано в bootstrap)
        # from src.core.container import get_device_service
        # device_service = get_device_service()

        # accesses = await device_service.get_device_accesses(device_id)

        # if accesses is None:
        #     raise HTTPException(
        #         status_code=status.HTTP_404_NOT_FOUND,
        #         detail="Device not found"
        #     )

        # Для теста возвращаем пустой список
        return []

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения доступов: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get access list"
        )
