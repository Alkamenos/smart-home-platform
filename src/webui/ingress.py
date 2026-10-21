"""Работа платформы за ingress Home Assistant (B79).

Аддон открывается из боковой панели Home Assistant по пути
``/api/hassio_ingress/<token>/``. Supervisor проксирует запросы к платформе и
присылает префикс в заголовке ``X-Ingress-Path``.

Без поддержки префикса интерфейс ломается: абсолютные ссылки на ``/_next/...``
и запросы ``/api/...`` уходят в корень домена, то есть в сам Home Assistant, а не
в аддон. Поэтому:

* middleware снимает префикс с пути запроса (прокси может прислать путь как с
  ним, так и без него) и кладёт префикс в состояние запроса;
* раздача статики подставляет в HTML ``window.__INGRESS_PATH__`` и дописывает
  префикс к абсолютным ссылкам на файлы интерфейса — с ним браузер грузит
  ``_next`` и открывает страницы снова через ingress;
* интерфейс берёт префикс из ``window.__INGRESS_PATH__`` для запросов к API и
  для WebSocket (``lib/api.ts``, ``lib/ws.ts``).

Что остаётся ограничением: клиентские переходы Next (app router) строят адреса
без префикса. Если такой переход не удаётся, Next перезагружает страницу, и она
открывается уже с префиксом; поэтому первая версия ingress работает, но часть
переходов может идти полной загрузкой. Это записано в BACKLOG B79.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


#: Заголовок, которым Supervisor называет префикс ingress.
INGRESS_PATH_HEADER = "x-ingress-path"

#: Имя глобальной переменной, из которой интерфейс берёт префикс.
INGRESS_GLOBAL = "__INGRESS_PATH__"

#: Абсолютный путь в строке страницы: `"/…"`, но не `"//…"`.
#: Пробелы, `<` и `>` исключены: иначе шаблон перешагнёт границу тегов
#: (проверено живьём: `type="image/x-icon"/>` и следующий `src="` склеивались).
_ABSOLUTE_PATH = re.compile(r'"(/(?!/)[^"<> ]*)"')


def ingress_path(headers: Headers) -> str:
    """Префикс ingress из заголовков запроса.

    Args:
        headers: Заголовки запроса.

    Returns:
        Префикс без хвостового слэша (``""``, если запрос не через ingress).
    """
    raw = headers.get(INGRESS_PATH_HEADER) or ""
    value = str(raw).strip()
    if not value.startswith("/"):
        return ""
    return value.rstrip("/")


def _strip_prefix(scope: dict[str, Any], prefix: str) -> None:
    """Снять префикс ingress с пути запроса.

    Supervisor может прислать путь и с префиксом, и без: снимаем, только если он
    там есть. Так обработчик экспортирует один и тот же путь в обоих случаях.

    Args:
        scope: Область ASGI-запроса (изменяется на месте).
        prefix: Префикс ingress.

    Returns:
        Ничего.
    """
    path = str(scope.get("path") or "")
    if path == prefix or path.startswith(prefix + "/"):
        scope["path"] = path[len(prefix) :] or "/"
    raw_path = scope.get("raw_path")
    if isinstance(raw_path, bytes) and (
        raw_path == prefix.encode() or raw_path.startswith(prefix.encode() + b"/")
    ):
        scope["raw_path"] = raw_path[len(prefix) :] or b"/"


class IngressMiddleware:
    """Запомнить префикс ingress и снять его с пути запроса.

    Args:
        app: ASGI-приложение.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Обработать запрос.

        Args:
            scope: Область ASGI-запроса.
            receive: Приёмник сообщений.
            send: Отправитель сообщений.

        Returns:
            Ничего.
        """
        if scope.get("type") in {"http", "websocket"}:
            prefix = ingress_path(Headers(scope=scope))
            if prefix:
                scope = dict(scope)
                state = dict(scope.get("state") or {})
                state["ingress_path"] = prefix
                scope["state"] = state
                _strip_prefix(scope, prefix)
        await self.app(scope, receive, send)


def with_ingress(html: str, prefix: str) -> str:
    """Подставить префикс ingress в HTML-страницу.

    Переписываются **все** абсолютные пути в строках страницы, а не только
    `href`/`src`: Next кладёт адреса `_next` ещё и в данные гидратации
    (`self.__next_f.push([1,"…/_next/…"])`), и без них браузер запросил бы
    часть файлов у корня домена. Уже префиксованные пути не трогаются — иначе
    получился бы двойной префикс.

    Args:
        html: Содержимое страницы.
        prefix: Префикс ingress (без хвостового слэша).

    Returns:
        Страница с глобальной переменной и префиксом у абсолютных путей.
    """

    def _prefixed(match: re.Match[str]) -> str:
        path = match.group(1)
        if path == prefix or path.startswith(prefix + "/"):
            return f'"{path}"'
        return f'"{prefix}{path}"'

    html = _ABSOLUTE_PATH.sub(_prefixed, html)
    script = f"<script>window.{INGRESS_GLOBAL}={json.dumps(prefix)};</script>"
    if "<head>" in html:
        return html.replace("<head>", "<head>" + script, 1)
    return script + html


class IngressStaticFiles(StaticFiles):
    """Статика интерфейса, которая умеет жить под префиксом ingress.

    Файлы отдаются как обычно; HTML-страницы правятся на лету — иначе браузер
    запросит ``_next`` у корня домена, то есть у Home Assistant.
    """

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Response:
        """Отдать файл, подставив префикс в HTML.

        Args:
            path: Путь внутри каталога сборки.
            scope: Область ASGI-запроса.

        Returns:
            Ответ статики.
        """
        response = await super().get_response(path, scope)
        prefix = ingress_path(Headers(scope=scope))
        if not prefix or scope.get("method") == "HEAD":
            return response
        if response.media_type != "text/html":
            return response
        file_path = getattr(response, "path", None)
        if not file_path:
            return response
        html = Path(file_path).read_text(encoding="utf-8")
        return Response(content=with_ingress(html, prefix), media_type="text/html")
