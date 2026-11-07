"""Shared device route helpers (spec 018, T059)."""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request, status

from webui.routes.devices.deps import get_device_service


logger = logging.getLogger(__name__)

_ROLE_VIEWER: Literal["viewer"] = "viewer"
_ROLE_CONTROLLER: Literal["controller"] = "controller"
_ROLE_ADMIN: Literal["admin"] = "admin"


def _is_admin_request(request: Request) -> bool:
    """Определяет, помечен ли запрос как пришедший от глобального администратора.

    Единая точка чтения признака для всех device-endpoints: и для одиночных
    операций (`_require_access_or_403`), и для списка устройств. Берётся из
    ``request.state`` (заполнил middleware) с фоллбэком на заголовок
    ``X-Is-Admin`` — сам список middleware не проходит, поэтому заголовок для
    него остаётся единственным источником.

    Args:
        request: HTTP запрос

    Returns:
        True, если запрос помечен как от глобального администратора.
    """
    is_admin: bool = getattr(request.state, "is_admin", False)
    actor = getattr(request.state, "actor", None)
    return is_admin or bool(actor is not None and actor.is_owner)


async def _require_access_or_403(
    request: Request,
    device_id: UUID,
    required_role: Literal["viewer", "controller", "admin"],
) -> None:
    """Проверяет роль пользователя на операцию над устройством (US1/T006).

    Идентификация берётся из request.state (заполнил middleware) с фоллбэком
    на заголовки. Не-админ без записи доступа (роль ниже требуемой) → 403.

    Args:
        request: HTTP запрос
        device_id: ID устройства
        required_role: Минимальная роль (viewer/controller/admin)

    Raises:
        HTTPException: 403 если доступ не пройден.
    """
    user_id = getattr(request.state, "user_id", None) or request.headers.get("X-User-ID")
    if _is_admin_request(request):
        return
    if not user_id:
        # Middleware уже отбил бы такой запрос; страховка
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-User-ID header"
        )
    service = get_device_service(request)
    allowed = await service.check_device_access(device_id, user_id, required_role=required_role)
    if not allowed:
        logger.warning(
            f"Access denied: user {user_id} -> device {device_id} (requires {required_role})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )
