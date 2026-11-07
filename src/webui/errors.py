"""Единый конверт ошибок внешних операций (спека 018, US5).

Каждый отказ API возвращает JSON с кодом, сообщением и `trace_id`. Внутренние
пути, трассировки и секреты в ответ не попадают.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from core.errors import PlatformError
from webui.middleware_request_id import TRACE_HEADER, accept_trace_id


#: HTTP-статус → стабильный машинный код.
_STATUS_CODES: dict[int, str] = {
    400: "validation_failed",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_failed",
    502: "upstream_unavailable",
    503: "upstream_unavailable",
    500: "internal_error",
}


def _trace_id(request: Request) -> str:
    """Идентификатор запроса для ответа и журнала.

    Args:
        request: HTTP-запрос.

    Returns:
        Безопасный идентификатор из middleware либо заголовка.
    """
    existing = getattr(request.state, "trace_id", None)
    if isinstance(existing, str) and existing:
        return existing
    return accept_trace_id(request.headers.get(TRACE_HEADER))


def error_envelope(
    *,
    code: str,
    message: str,
    trace_id: str,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Собрать тело ошибки по контракту.

    Args:
        code: Машинный код.
        message: Человеческое объяснение.
        trace_id: Идентификатор запроса.
        fields: Ошибки по полям формы.

    Returns:
        Конверт ``{"error": {...}}``.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "fields": fields or [],
            "trace_id": trace_id,
        }
    }


def _http_exception_response(request: Request, exc: HTTPException) -> JSONResponse:
    """Ответ на HTTPException в едином конверте.

    Args:
        request: HTTP-запрос.
        exc: Исключение маршрута.

    Returns:
        JSON-ответ с конвертом.
    """
    trace_id = _trace_id(request)
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or _STATUS_CODES.get(exc.status_code, "internal_error"))
        message = str(detail.get("message") or detail.get("detail") or "Ошибка запроса")
        fields = detail.get("fields")
    else:
        code = _STATUS_CODES.get(exc.status_code, "internal_error")
        message = str(detail or "Ошибка запроса")
        fields = None
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(
            code=code,
            message=message,
            trace_id=trace_id,
            fields=fields if isinstance(fields, list) else None,
        ),
        headers={TRACE_HEADER: trace_id},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Подключить обработчики ошибок к приложению.

    Args:
        app: FastAPI-приложение.
    """

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return _http_exception_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        trace_id = _trace_id(request)
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "неверное значение")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_envelope(
                code="validation_failed",
                message="Входные данные неверны",
                trace_id=trace_id,
                fields=fields,
            ),
            headers={TRACE_HEADER: trace_id},
        )

    @app.exception_handler(PlatformError)
    async def _platform_error(request: Request, exc: PlatformError) -> JSONResponse:
        trace_id = _trace_id(request)
        return JSONResponse(
            status_code=exc.http_status,
            content=error_envelope(
                code=exc.code,
                message=exc.message,
                trace_id=trace_id,
            ),
            headers={TRACE_HEADER: trace_id},
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        trace_id = _trace_id(request)
        logger.opt(exception=exc).error(f"[{trace_id}] Непредвиденная ошибка API")
        return JSONResponse(
            status_code=500,
            content=error_envelope(
                code="internal_error",
                message="Внутренняя ошибка платформы",
                trace_id=trace_id,
            ),
            headers={TRACE_HEADER: trace_id},
        )
