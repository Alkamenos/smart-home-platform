"""Технические логи платформы для интерфейса (спека 017, US6, FR-028).

Логи держит ``LogStore`` веб-слоя (в памяти, кольцевой буфер). Отдельного
журнала событий автоматики здесь нет — он на ``/api/v1/events``; это именно
технические сообщения процесса: запуск, предупреждения, ошибки.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["logs"])

#: Сколько сообщений отдаётся по умолчанию и максимум.
DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


@router.get("/api/v1/logs", response_class=JSONResponse)
async def get_logs(
    request: Request,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> JSONResponse:
    """Отдать последние технические сообщения платформы.

    Args:
        request: Входящий HTTP-запрос.
        limit: Сколько сообщений вернуть не больше.

    Returns:
        JSON ``{"count": N, "logs": [{timestamp, level, message}]}`` либо 503,
        если хранилище логов недоступно.
    """
    store = getattr(request.app.state, "log_store", None)
    if store is None:
        return JSONResponse(
            {"error": "Хранилище логов недоступно: платформа не собрана"},
            status_code=503,
        )
    logs = store.get_logs(limit)
    return JSONResponse({"count": len(logs), "logs": logs})
