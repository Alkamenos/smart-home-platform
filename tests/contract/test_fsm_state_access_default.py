"""Дефолт доступа к состояниям автоматов был «на отказ»: без прав — всё видно.

Очередь 5 продакшен-плана, пункт «инверсия дефолта в /api/fsm/state».

`_resolve_accessible_device_ids` возвращала `None` («без фильтрации») в трёх
случаях, и все три означали полный доступ:

- заголовок `X-User-ID` отсутствует → видно всё;
- сервис устройств недоступен → видно всё;
- фильтрация упала с исключением → видно всё.

Самое существенное — первое: запрос без единого заголовка получал состояния
всех устройств. Защитой это не являлось: заголовок всё равно подделывается
одним значением, но клиент, который просто не знает про заголовки (браузер,
чужой скрипт), получал полный доступ молча.

Причина, по которой дефект нельзя было исправить одной правкой сервера:
`dashboard.html` — единственный шаблон без `data-user-id` на `<body>`, его
`authHeaders()` возвращал `{}`, а маршрут не передавал идентичность в контекст.
То есть дашборд сам зависел от «на отказ». Поэтому проверяется и серверная
часть, и клиентская.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


TEMPLATES = Path(__file__).resolve().parent.parent.parent / "src" / "webui" / "templates"


@pytest.fixture
def client() -> TestClient:
    """Приложение с идентичностью администратора."""
    from main import app

    return TestClient(app, headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"})


@pytest.fixture
def anonymous_client() -> TestClient:
    """Приложение без единого заголовка."""
    from main import app

    return TestClient(app)


class TestAnonymousAccessIsNotFullAccess:
    """Отсутствие идентичности не должно давать доступ ко всему."""

    def test_request_without_headers_does_not_return_200_with_all_states(
        self, client: TestClient, anonymous_client: TestClient
    ) -> None:
        """Запрос без заголовков не отдаёт состояния всех устройств.

        Проверяется сравнением с admin-доступом: если бы анонимный ответ был
        таким же, дефект считался бы исправленным.
        """
        admin_states = client.get("/api/fsm/state").json()["states"]
        if not admin_states:
            pytest.skip("в приложении нет автоматов — сравнивать нечего")

        response = anonymous_client.get("/api/fsm/state")

        assert response.status_code != 200 or not response.json().get("states"), (
            "анонимный запрос получил 200 с состояниями: доступ «на отказ» "
            f"(админ видит {len(admin_states)}, аноним — "
            f"{len(response.json().get('states', []))})"
        )


class TestFailClosedOnBrokenService:
    """Сбой сервиса устройств не должен превращаться в полный доступ."""

    def test_missing_device_service_does_not_grant_full_access(self, client: TestClient) -> None:
        """Без сервиса устройств — 503, а не все состояния.

        Раньше при `device_service is None` возвращалось `None`, то есть
        «без фильтрации»: сломанный сервис выдавал больше прав, чем рабочий.
        """
        original = getattr(client.app.state, "device_service", None)
        # Считаем эталон ДО поломки: со сломанным сервисом эндпоинт честно
        # отвечает отказом и поля states в ответе уже нет.
        admin_states = len(client.get("/api/fsm/state").json()["states"])

        client.app.state.device_service = None
        try:
            response = client.get("/api/fsm/state")
        finally:
            client.app.state.device_service = original

        assert not (response.status_code == 200 and response.json().get("count") == admin_states), (
            "сломанный сервис устройств выдал полный доступ к состояниям"
        )

    def test_failing_filter_does_not_grant_full_access(self, client: TestClient) -> None:
        """Исключение при фильтрации не должно открывать доступ.

        Раньше `except Exception: return None` превращал любую ошибку в
        «показать всё». Ошибка фильтрации — это отказ, а не разрешение.
        """
        original = getattr(client.app.state, "device_service", None)

        class Exploding:
            async def get_user_accessible_devices(self, _user_id: str) -> list[Any]:
                raise RuntimeError("хранилище недоступно")

        client.app.state.device_service = Exploding()
        try:
            admin_states = len(client.get("/api/fsm/state").json()["states"])
            response = TestClient(
                client.app, headers={"X-User-ID": "user_without_devices", "X-Is-Admin": "false"}
            ).get("/api/fsm/state")
        finally:
            client.app.state.device_service = original

        assert not (response.status_code == 200 and response.json().get("count") == admin_states), (
            "упавшая фильтрация выдала полный доступ к состояниям"
        )


class TestDashboardSendsItsIdentity:
    """Дашборд обязан передавать идентичность, как это делает index.html.

    Без этого сервер не может отличить пользователя от постороннего запроса,
    и исправление дефолта сломало бы сам дашборд.
    """

    def test_dashboard_body_carries_identity_attributes(self) -> None:
        """На `<body>` есть data-user-id и data-user-is-admin."""
        source = (TEMPLATES / "dashboard.html").read_text(encoding="utf-8")

        body = re.search(r"<body[^>]*>", source)
        assert body, "не найден тег <body> в dashboard.html"
        tag = body.group(0)

        assert "data-user-id" in tag, (
            "у dashboard.html нет data-user-id: сервер не сможет определить, "
            "кто делает запрос, и вернёт отказ вместо данных"
        )
        assert "data-user-is-admin" in tag, "у dashboard.html нет data-user-is-admin"

    def test_dashboard_auth_headers_are_not_empty(self) -> None:
        """authHeaders() возвращает настоящие заголовки, а не пустой объект."""
        source = (TEMPLATES / "dashboard.html").read_text(encoding="utf-8")

        body_match = re.search(r"function authHeaders\(\)\s*\{(.*?)\n\s*\}", source, re.S)
        assert body_match, "не найдена функция authHeaders() в dashboard.html"
        body = body_match.group(1)

        assert "X-User-ID" in body, (
            "authHeaders() не отправляет X-User-ID — запрос уйдёт анонимным, "
            "и после исправления дефолта дашборд покажет пустую страницу"
        )
        assert "X-Is-Admin" in body, "authHeaders() не отправляет X-Is-Admin"

    def test_dashboard_route_passes_identity_to_template(self) -> None:
        """Маршрут дашборда передаёт user_id и user_is_admin в контекст."""
        source = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "webui"
            / "routes"
            / "__init__.py"
        ).read_text(encoding="utf-8")

        response_block = re.search(r'"dashboard\.html",\s*\{(.*?)\}', source, re.S)
        assert response_block, "не найден отдача dashboard.html"
        context = response_block.group(1)

        assert "user_id" in context, (
            "маршрут дашборда не передаёт user_id: шаблон получит пустую "
            "идентичность и не сможет построить заголовки"
        )
        assert "user_is_admin" in context, "маршрут дашборда не передаёт user_is_admin"

    def test_dashboard_page_actually_contains_rendered_identity(self) -> None:
        """Живой ответ дашборда содержит идентичность, а не пустые значения."""
        response = TestClient(__import__("main").app).get("/dashboard")

        assert response.status_code == 200
        body = response.text
        body_tag = re.search(r"<body[^>]*>", body)
        assert body_tag, "в ответе дашборда нет <body>"
        assert "data-user-id" in body_tag.group(0), (
            "отрисованный дашборд не содержит data-user-id — идентичность теряется"
        )
