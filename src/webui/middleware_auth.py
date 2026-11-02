"""Глобальная граница управления (спека 018, US2).

Default deny: изменяющие и управляющие запросы разрешены только из доверенной
сети или через ingress. Заголовки клиента прав не повышают. Состояние
(`/health`, `/ready`, `/metrics`) доступно по явному allowlist.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from urllib.parse import urlsplit

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from webui.security.identity import resolve_actor


#: Пути, доступные без доверенного источника.
ALLOWLIST = frozenset({"/health", "/ready", "/metrics", "/api/v1/session"})

#: Префиксы, которые считаются управляющей поверхностью.
MANAGEMENT_PREFIXES = ("/api/",)

#: Документация API не должна быть доступна из недоверенной сети.
MANAGEMENT_PATHS = frozenset({"/openapi.json", "/docs", "/redoc"})

#: Методы, меняющие состояние.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _requires_management(path: str) -> bool:
    """Требует ли путь доверенного источника.

    Args:
        path: Путь запроса.

    Returns:
        True, если путь управляющий.
    """
    normalized = path.rstrip("/") or "/"
    if normalized in ALLOWLIST:
        return False
    if normalized in MANAGEMENT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in MANAGEMENT_PREFIXES)


def _cross_origin(request: Request) -> bool:
    """Пришёл ли изменяющий запрос с чужого Origin.

    Проверка защищает от CSRF: без пароля браузер владельца — единственная
    защита от чужой страницы, которая попытается изменить дом.

    Args:
        request: Входящий запрос.

    Returns:
        True, если Origin не совпадает с хостом платформы.
    """
    if request.method not in MUTATING_METHODS:
        return False
    if request.headers.get("X-Ingress-Path"):
        # Ingress HA уже отделяет внешний адрес; Origin там — адрес панели HA.
        return False
    origin = request.headers.get("Origin")
    if not origin:
        return False
    parsed = urlsplit(origin)
    host_header = request.headers.get("Host", "")
    expected = {request.url.hostname, host_header.split(":", 1)[0]}
    return parsed.hostname not in expected


def _forbidden(request: Request, message: str) -> JSONResponse:
    """Собрать единый отказ.

    Args:
        request: Входящий запрос.
        message: Человеческое объяснение.

    Returns:
        JSON-ответ 403.
    """
    trace_id = getattr(request.state, "trace_id", "")
    return JSONResponse(
        {
            "error": {
                "code": "forbidden",
                "message": message,
                "trace_id": trace_id,
            }
        },
        status_code=403,
    )


class ManagementAccessMiddleware(BaseHTTPMiddleware):
    """Проверить источник и Origin для управляющих запросов."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Обработать запрос.

        Args:
            request: Входящий запрос.
            call_next: Следующий обработчик.

        Returns:
            Ответ либо отказ 403.
        """
        actor = resolve_actor(request)
        request.state.actor = actor

        if _requires_management(request.url.path) and not actor.trusted:
            host = request.client.host if request.client is not None else "?"
            logger.warning(
                f"Управление отклонено: {request.method} {request.url.path} "
                f"из недоверенного источника {host} "
                f"(trace_id={getattr(request.state, 'trace_id', '')})"
            )
            return _forbidden(request, "Управление доступно только из доверенной сети")

        if actor.trusted and _cross_origin(request):
            logger.warning(
                f"Управление отклонено: {request.method} {request.url.path} "
                f"с чужого Origin {request.headers.get('Origin')!r} "
                f"(trace_id={getattr(request.state, 'trace_id', '')})"
            )
            return _forbidden(request, "Изменяющий запрос пришёл с чужого источника")

        return await call_next(request)
