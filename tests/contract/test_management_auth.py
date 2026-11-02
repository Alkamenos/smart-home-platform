"""Граница управления: доверенная сеть и default deny (спека 018, US2).

Проверяется не «есть ли заголовок», а откуда пришёл запрос: изменять дом можно
только из доверенной сети или через ingress. Подделанный признак администратора
не помогает недоверенному клиенту.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


UNTRUSTED = ("203.0.113.9", 12345)


def _manifest() -> dict[str, Any]:
    """Минимальный корректный манифест.

    Returns:
        Словарь для PUT.
    """
    return {
        "instance": {"id": "probe", "name": "Probe", "owner": "probe", "created_at": ""},
        "version": 1,
        "rooms": [],
    }


def _untrusted(app: Any) -> TestClient:
    """Клиент из недоверенной сети.

    Args:
        app: Приложение.

    Returns:
        HTTP-клиент.
    """
    return TestClient(app, client=UNTRUSTED)


def test_untrusted_cannot_change_manifest(isolated_app: Any) -> None:
    """Из недоверенной сети манифест не меняется."""
    response = _untrusted(isolated_app).put("/api/v1/manifest", json=_manifest())

    assert response.status_code == 403, response.text


def test_spoofed_admin_header_does_not_help_untrusted(isolated_app: Any) -> None:
    """Признак администратора от клиента не повышает права."""
    response = _untrusted(isolated_app).put(
        "/api/v1/manifest",
        json=_manifest(),
        headers={"X-Is-Admin": "true", "X-User-ID": "owner"},
    )

    assert response.status_code == 403, response.text


def test_untrusted_cannot_send_device_command(isolated_app: Any) -> None:
    """Команда прибору из недоверенной сети отклоняется до маршрута."""
    response = _untrusted(isolated_app).post(
        "/api/v1/devices/00000000-0000-0000-0000-000000000000/command",
        json={"command": "turn_on"},
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize("path", ["/health", "/ready", "/metrics"])
def test_state_endpoints_are_available_untrusted(isolated_app: Any, path: str) -> None:
    """Состояние доступно мониторингу по явному allowlist."""
    response = _untrusted(isolated_app).get(path)

    assert response.status_code != 403, f"{path}: граница управления закрыла состояние"


def test_trusted_network_can_change_manifest(isolated_app: Any) -> None:
    """Из доверенной сети изменение проходит без пароля."""
    with TestClient(isolated_app) as client:
        response = client.put(
            "/api/v1/manifest",
            json=_manifest(),
            params={"allow_removal": "true"},
        )

    assert response.status_code == 200, response.text


def test_cross_origin_write_is_denied(isolated_app: Any) -> None:
    """Запрос из браузера с чужим Origin не меняет дом."""
    with TestClient(isolated_app) as client:
        response = client.put(
            "/api/v1/manifest",
            json=_manifest(),
            headers={"Origin": "http://evil.example"},
        )

    assert response.status_code == 403, response.text


def test_same_origin_write_is_allowed(isolated_app: Any) -> None:
    """Свой Origin не мешает обычной работе."""
    with TestClient(isolated_app) as client:
        response = client.put(
            "/api/v1/manifest",
            json=_manifest(),
            headers={"Origin": "http://testserver"},
            params={"allow_removal": "true"},
        )

    assert response.status_code == 200, response.text
