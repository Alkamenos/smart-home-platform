"""Ingress Home Assistant: префикс пути и статика интерфейса (B79).

Аддон открывается из боковой панели Home Assistant по пути
`/api/hassio_ingress/<token>/`. Без поддержки префикса интерфейс ломается:
абсолютные ссылки на `_next` и запросы `/api/...` уходят в корень домена — в сам
Home Assistant, а не в аддон.

Проверки держат четыре вещи:

* путь с префиксом доходит до маршрута (префикс снимается);
* без заголовка поведение не меняется (обычный доступ по порту);
* HTML получает `window.__INGRESS_PATH__` и префикс у абсолютных ссылок;
* не-HTML файлы не трогаются — иначе сломались бы размеры и содержимое.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from webui.ingress import IngressMiddleware, IngressStaticFiles


PREFIX = "/api/hassio_ingress/token"


def _app(static_dir: Path | None = None) -> FastAPI:
    """Приложение с маршрутом и (необязательно) статикой.

    Args:
        static_dir: Каталог сборки интерфейса.

    Returns:
        Приложение с middleware ingress.
    """
    app = FastAPI()

    @app.get("/api/v1/session")
    async def session() -> JSONResponse:
        """Простой маршрут вместо настоящей сессии.

        Returns:
            JSON с признаком сессии.
        """
        return JSONResponse({"user_id": "admin_user"})

    if static_dir is not None:
        app.mount("/", IngressStaticFiles(directory=str(static_dir), html=True), name="spa")

    app.add_middleware(IngressMiddleware)
    return app


def _index(directory: Path) -> None:
    """Положить страницу с абсолютными ссылками, как у Next.

    Args:
        directory: Каталог сборки.

    Returns:
        Ничего.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(
        "<!doctype html><html><head>"
        '<link rel="stylesheet" href="/_next/static/app.css">'
        '</head><body><script src="/_next/static/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (directory / "app.js").write_text("console.log('/_next/static/');", encoding="utf-8")


class TestPrefixIsStripped:
    """Путь с префиксом ingress доходит до маршрута."""

    def test_prefixed_path_reaches_the_route(self) -> None:
        """`<prefix>/api/v1/session` — это `api/v1/session`."""
        client = TestClient(_app())

        response = client.get(f"{PREFIX}/api/v1/session", headers={"X-Ingress-Path": PREFIX})

        assert response.status_code == 200
        assert response.json()["user_id"] == "admin_user"

    def test_plain_path_still_works_with_header(self) -> None:
        """Прокси может прислать путь и без префикса — маршрут тот же."""
        client = TestClient(_app())

        response = client.get("/api/v1/session", headers={"X-Ingress-Path": PREFIX})

        assert response.status_code == 200

    def test_without_header_nothing_changes(self) -> None:
        """Обычный доступ по порту работает как прежде."""
        client = TestClient(_app())

        assert client.get("/api/v1/session").status_code == 200
        assert client.get(f"{PREFIX}/api/v1/session").status_code == 404


class TestHtmlCarriesThePrefix:
    """Страница получает префикс, чтобы браузер грузил файлы из аддона."""

    def test_page_gets_global_and_prefixed_links(self, tmp_path: Path) -> None:
        """В HTML есть `window.__INGRESS_PATH__` и префикс у `_next`."""
        _index(tmp_path)
        client = TestClient(_app(tmp_path))

        response = client.get("/", headers={"X-Ingress-Path": PREFIX})
        html = response.text

        assert response.status_code == 200
        assert f'window.__INGRESS_PATH__="{PREFIX}"' in html
        assert f'href="{PREFIX}/_next/static/app.css"' in html
        assert f'src="{PREFIX}/_next/static/app.js"' in html

    def test_page_without_header_is_untouched(self, tmp_path: Path) -> None:
        """Без ingress страница отдаётся как собрана."""
        _index(tmp_path)
        client = TestClient(_app(tmp_path))

        html = client.get("/").text

        assert "__INGRESS_PATH__" not in html
        assert 'href="/_next/static/app.css"' in html

    def test_assets_are_not_rewritten(self, tmp_path: Path) -> None:
        """JS-файл отдаётся байт в байт: переписывать содержимое нельзя."""
        _index(tmp_path)
        client = TestClient(_app(tmp_path))

        body = client.get("/app.js", headers={"X-Ingress-Path": PREFIX}).text

        assert body == "console.log('/_next/static/');"

    def test_inline_flight_data_is_prefixed(self, tmp_path: Path) -> None:
        """Адреса `_next` в данных гидратации тоже получают префикс.

        Next кладёт часть адресов не в `href`/`src`, а в строки
        `self.__next_f.push(...)`: без префикса браузер запросил бы их у корня
        домена.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        _index(tmp_path)
        page = tmp_path / "index.html"
        page.write_text(
            page.read_text(encoding="utf-8").replace(
                "</head>",
                '<script>self.__next_f.push([1,"/_next/static/chunk.js"])</script></head>',
            ),
            encoding="utf-8",
        )
        client = TestClient(_app(tmp_path))

        html = client.get("/", headers={"X-Ingress-Path": PREFIX}).text

        assert f'"{PREFIX}/_next/static/chunk.js"' in html

    def test_already_prefixed_paths_are_not_doubled(self, tmp_path: Path) -> None:
        """Повторная страница с префиксом не даёт `prefix/prefix`.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        _index(tmp_path)
        page = tmp_path / "index.html"
        page.write_text(
            page.read_text(encoding="utf-8").replace(
                "</head>", f'<script src="{PREFIX}/_next/static/app.js"></script></head>'
            ),
            encoding="utf-8",
        )
        client = TestClient(_app(tmp_path))

        html = client.get("/", headers={"X-Ingress-Path": PREFIX}).text

        assert f"{PREFIX}{PREFIX}" not in html

    def test_tag_boundaries_are_not_glued(self, tmp_path: Path) -> None:
        """Шаблон не перешагивает границу тегов: `type="…"/>` остаётся целым.

        Живая находка 21.10: жадный шаблон склеил закрывающий `/>` со следующим
        `src="…"` и вставил префикс в середину тега.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        _index(tmp_path)
        page = tmp_path / "index.html"
        page.write_text(
            page.read_text(encoding="utf-8").replace(
                '<link rel="stylesheet" href="/_next/static/app.css">',
                '<link rel="icon" href="/favicon.ico" type="image/x-icon"/>',
            ),
            encoding="utf-8",
        )
        client = TestClient(_app(tmp_path))

        html = client.get("/", headers={"X-Ingress-Path": PREFIX}).text

        assert 'type="image/x-icon"/>' in html
        assert f'href="{PREFIX}/favicon.ico"' in html
