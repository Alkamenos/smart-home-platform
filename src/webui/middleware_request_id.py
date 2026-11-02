"""Сквозной идентификатор запроса (спека 018, D5).

Один `trace_id` связывает HTTP-запрос, решение автомата, команду и результат.
Заголовок принимается только в безопасном виде: иначе в журнал можно подсунуть
что угодно.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


TRACE_HEADER = "X-Trace-ID"

#: Допустимый вид внешнего идентификатора.
_TRACE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_trace_id() -> str:
    """Сгенерировать короткий идентификатор.

    Returns:
        Восемь шестнадцатеричных символов.
    """
    return uuid4().hex[:8]


def accept_trace_id(raw: str | None) -> str:
    """Принять внешний идентификатор или создать новый.

    Args:
        raw: Значение заголовка `X-Trace-ID`.

    Returns:
        Безопасный идентификатор.
    """
    if raw and _TRACE_RE.match(raw):
        return raw
    return new_trace_id()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Проставить `trace_id` запросу и ответу."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Обработать запрос.

        Args:
            request: Входящий запрос.
            call_next: Следующий обработчик.

        Returns:
            Ответ с заголовком `X-Trace-ID`.
        """
        trace_id = accept_trace_id(request.headers.get(TRACE_HEADER))
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response
