"""Чистка мусора во вспомогательных элементах (BACKLOG B77).

Раздел ничего не удаляет по своей воле: он показывает, какие вспомогательные
элементы дома не используются **по сведениям платформы**, и почему так решено.
Удаление — решение человека: оно необратимо, а «сломалось тихо, заметили
вечером» дороже выгоды от автоматики.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["cleanup"])


def _service(request: Request) -> Any:
    """Взять службу чистки из контейнера.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Служба чистки либо ``None``, если она не собрана.
    """
    container = getattr(request.app.state, "container", None)
    return getattr(container, "helper_cleanup", None)


@router.get("/api/v1/system/cleanup")
async def cleanup(request: Request, refresh: bool = False) -> JSONResponse:
    """Вспомогательные элементы дома и признак использования.

    Args:
        request: Входящий HTTP-запрос.
        refresh: Пересобрать снимок, не дожидаясь истечения срока годности.

    Returns:
        JSON со снимком: ``generated_at``, ``counts``, ``sources`` и ``helpers`` —
        каждый элемент с вердиктом и причинами.
    """
    service = _service(request)
    if service is None:
        return JSONResponse(
            {"generated_at": None, "counts": {}, "sources": {}, "helpers": []},
        )
    report = await service.sweep(force=refresh)
    return JSONResponse(report)
