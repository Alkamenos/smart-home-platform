"""Идентичность интерфейса: GET /api/v1/session (спека 017, US5).

Проверяется то, ради чего эндпоинт заведён: статический интерфейс узнаёт, кто он
и что ему можно. При отсутствии заголовков берётся пользователь по умолчанию —
модель доступа в локальной сети не меняется.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui.routes.session import router


def _client(default_user_id: str = "admin_user", default_user_is_admin: bool = True) -> TestClient:
    """Клиент с маршрутом сессии.

    Args:
        default_user_id: Пользователь по умолчанию.
        default_user_is_admin: Админ ли пользователь по умолчанию.

    Returns:
        Тестовый клиент.
    """
    app = FastAPI()
    app.include_router(router)
    app.state.default_user_id = default_user_id
    app.state.default_user_is_admin = default_user_is_admin
    return TestClient(app)


def test_session_should_use_headers_when_present() -> None:
    """Заголовки запроса перекрывают пользователя по умолчанию."""
    response = _client().get(
        "/api/v1/session",
        headers={"X-User-ID": "guest", "X-Is-Admin": "false"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "guest"
    assert body["is_admin"] is False


def test_session_should_fall_back_to_default_user() -> None:
    """Без заголовков отдаётся пользователь по умолчанию."""
    response = _client(default_user_id="admin_user", default_user_is_admin=True).get(
        "/api/v1/session"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "admin_user"
    assert body["is_admin"] is True
