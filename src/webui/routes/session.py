"""Идентичность текущего запроса для интерфейса (спека 017, FR-024/US5).

Одно место, где интерфейс узнаёт, кто он и что ему можно. Раньше это зашивал в
разметку серверный рендер (атрибуты ``<body>``); статическому интерфейсу нужен
явный источник. Модель доступа не меняется: значения по-прежнему приходят из
запроса (заголовки), а при их отсутствии берётся пользователь по умолчанию,
заданный платформой (развёртывание в локальной сети).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["session"])


def _is_admin(request: Request) -> bool:
    """Определить администратора запроса.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        True, если запрос помечен как администратор.
    """
    header = request.headers.get("X-Is-Admin")
    if header is not None:
        return header.lower() == "true"
    return bool(getattr(request.app.state, "default_user_is_admin", False))


def _user_id(request: Request) -> str:
    """Определить идентификатор пользователя запроса.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Идентификатор из заголовка либо пользователь по умолчанию.
    """
    header = request.headers.get("X-User-ID")
    if header:
        return header
    return str(getattr(request.app.state, "default_user_id", "") or "")


@router.get("/api/v1/session", response_class=JSONResponse)
async def get_session(request: Request) -> JSONResponse:
    """Отдать идентичность и права текущего запроса.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON ``{"user_id", "is_admin", "display_name"}``.
    """
    user_id = _user_id(request)
    is_admin = _is_admin(request)
    return JSONResponse(
        {
            "user_id": user_id,
            "is_admin": is_admin,
            "display_name": user_id,
        }
    )
