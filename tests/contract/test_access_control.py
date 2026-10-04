"""
Контрактные тесты для управления доступом к устройствам.

Тесты проверяют контракт между клиентом и сервером для операций управления доступом
на основе ролей пользователей.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Что было не так (спека 009, T028)
---------------------------------
Фикстура `sample_device` возвращала словарь со **случайным** `uuid4()`, который
никогда не создавался в системе. Каждый тест этого файла обращался к
несуществующему устройству и получал `404`, а ассерты допускали
`[200, 404]` / `[403, 404]` — то есть проходили независимо от того, работает ли
разграничение прав. Тесты выглядели как контракт прав, но не проверяли прав:
отказ по правам и отсутствие устройства давали один и тот же наблюдаемый
результат.

Теперь `sample_device` создаёт настоящее устройство, а допуски заменены
конкретными ожиданиями: разграничение прав проверяется на существующем
устройстве, где «403» и «404» означают разные вещи.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app

    return TestClient(app)


@pytest.fixture
def current_user_id():
    """ID текущего пользователя для тестов."""
    return str(uuid4())


@pytest.fixture
def other_user_id():
    """ID другого пользователя для тестов."""
    return str(uuid4())


@pytest.fixture
def sample_source(client):
    """Фикстура для создания тестового источника."""
    payload = {
        "name": "Access Control Test Source",
        "url": "http://192.168.1.100:8123",
        "token": "access_control_token",
    }
    response = client.post("/api/v1/devices/sources", json=payload)
    return response.json() if response.status_code == 201 else None


@pytest.fixture
def sample_device(client, sample_source):
    """Настоящее устройство, посеянное в единый источник.

    Прежде фикстура возвращала словарь со случайным `uuid4()`, которого в
    системе не существовало: каждый тест файла получал `404` и проходил по
    допуску `[200, 404]`. Теперь устройство реально существует, поэтому отказ по
    правам (`403`) и его отсутствие (`404`) становятся различимыми.

    Args:
        client: HTTP-клиент теста.
        sample_source: Созданный источник.

    Returns:
        Словарь с идентификатором устройства и его полями.
    """
    from tests.helpers.device_factory import make_device, seed_device_in_service

    if not sample_source:
        return None

    device = make_device(ha_entity_id="light.test_access", name="Test Access Device")
    seed_device_in_service(client.app.state.device_service, device)
    return {
        "id": str(device.id),
        "ha_entity_id": device.ha_entity_id,
        "source_id": sample_source["id"],
        "name": device.name,
        "device_type": device.device_type,
        "status": device.status,
    }


class TestAccessControlAPI:
    """Тесты для контракта API управления доступом."""

    # T061: Контрактный тест для проверки прав доступа

    def test_get_device_without_access_returns_403(self, client, current_user_id, sample_device):
        """T061: Получение существующего устройства без прав возвращает 403.

        Раньше обращение шло к случайному `uuid4()`, то есть к несуществующему
        устройству, и допуск `[403, 404]` проходил по `404` — проверка прав не
        происходила вовсе. Теперь устройство существует, поэтому `403` и `404`
        означают разные вещи и выбирать можно ровно один код.
        """
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        response = client.get(f"/api/v1/devices/{device_id}", headers={"X-User-ID": "stranger"})

        assert response.status_code == 403, (
            f"ожидался 403 для существующего устройства без доступа: {response.text}"
        )

    def test_get_device_with_viewer_access(self, client, current_user_id, sample_device):
        """T061: Пользователь с ролью viewer может видеть устройство."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Выдаём доступ явно: без него проверка «с доступом» совпадала бы
        # с проверкой «без доступа».
        granted = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": current_user_id, "role": "viewer"},
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        assert granted.status_code == 201, granted.text

        response = client.get(
            f"/api/v1/devices/{device_id}", headers={"X-User-ID": current_user_id}
        )

        assert response.status_code == 200, f"ожидался 200: {response.text}"

    def test_execute_command_without_controller_access_returns_403(
        self, client, other_user_id, sample_device
    ):
        """T061: Отправка команды без прав controller возвращает 403."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Пользователь пытается отправить команду без прав
        payload = {"command_name": "turn_on"}

        response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json=payload,
            headers={"X-User-ID": other_user_id},
        )

        # Устройство существует, поэтому 403 означает именно отказ по правам.
        assert response.status_code == 403, (
            f"ожидался 403 для команды без роли controller: {response.text}"
        )

    def test_execute_command_with_controller_access(self, client, current_user_id, sample_device):
        """T061: Пользователь с ролью controller может отправить команду."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        granted = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": current_user_id, "role": "controller"},
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        assert granted.status_code == 201, granted.text

        # Пользователь с доступом controller отправляет команду
        payload = {"command_name": "turn_on"}

        response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json=payload,
            headers={"X-User-ID": current_user_id},
        )

        assert response.status_code == 202, f"ожидался 202 для роли controller: {response.text}"

    # T062: Контрактный тест для управления правами доступа

    def test_grant_access_to_device(self, client, current_user_id, other_user_id, sample_device):
        """T062: Администратор может назначить доступ пользователю."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Администратор назначает доступ пользователю
        payload = {
            "user_id": other_user_id,
            "role": "viewer",  # Роли: viewer, controller, admin
        }

        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json=payload,
            headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть 201 Created или 200 OK
        assert response.status_code in [200, 201]

        if response.status_code in [200, 201]:
            data = response.json()
            assert data.get("user_id") == other_user_id
            assert data.get("role") == "viewer"
            assert "device_id" in data
            assert "id" in data

    def test_grant_access_by_non_admin_returns_403(
        self, client, current_user_id, other_user_id, sample_device
    ):
        """T062: Обычный пользователь не может назначать доступ."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Обычный пользователь (не админ) пытается назначить доступ
        payload = {"user_id": other_user_id, "role": "viewer"}

        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json=payload,
            headers={"X-User-ID": current_user_id},  # Не админ
        )

        # Должен быть 403 Forbidden
        assert response.status_code == 403

    def test_revoke_access(self, client, current_user_id, other_user_id, sample_device):
        """T062: Администратор может отозвать доступ."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]
        granted = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": other_user_id, "role": "viewer"},
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        assert granted.status_code == 201, granted.text

        # Отзывается именно выданная запись, а не случайный идентификатор.
        revoke = client.delete(
            f"/api/v1/devices/{device_id}/access/{granted.json()['id']}",
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        assert revoke.status_code == 204, f"ожидался 204: {revoke.text}"

    def test_get_device_access_list(self, client, current_user_id, other_user_id, sample_device):
        """T062: Получение списка доступа к устройству."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Сначала выдаём доступ: проверка непустоты списка без выданного доступа
        # означала бы «устройства нет», а не «доступы перечисляются».
        granted = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": other_user_id, "role": "controller"},
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        assert granted.status_code == 201, granted.text

        # Администратор получает список доступа
        response = client.get(
            f"/api/v1/devices/{device_id}/access",
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )

        # Должен быть 200 OK
        assert response.status_code == 200, f"ожидался 200 для списка доступа: {response.text}"

        data = response.json()
        assert isinstance(data, list)
        assert data, "у выданного доступа должна быть хотя бы одна запись"
        # Каждая запись должна содержать информацию о доступе
        for access in data:
            assert "id" in access
            assert "user_id" in access
            assert "role" in access
            assert access["role"] in ["viewer", "controller", "admin"]

    def test_valid_roles(self, client, current_user_id, other_user_id, sample_device):
        """T062: Проверка что система поддерживает роли: viewer, controller, admin."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Тестируем все роли
        for role in ["viewer", "controller", "admin"]:
            payload = {"user_id": other_user_id, "role": role}

            response = client.post(
                f"/api/v1/devices/{device_id}/access",
                json=payload,
                headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
            )

            # Должен быть успешный ответ
            assert response.status_code in [200, 201]

    def test_invalid_role_returns_400(self, client, current_user_id, other_user_id, sample_device):
        """T062: Некорректная роль возвращает 400 Bad Request."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Пытаемся назначить некорректную роль
        payload = {"user_id": other_user_id, "role": "invalid_role"}

        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json=payload,
            headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть 400 Bad Request
        assert response.status_code == 400

    def test_grant_duplicate_updates_role_no_duplicates(
        self, client, current_user_id, other_user_id, sample_device
    ):
        """T008 (spec 004 US2): повторный grant той же паре обновляет роль, дубликатов нет."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]
        headers = {"X-User-ID": current_user_id, "X-Is-Admin": "true"}

        first = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": other_user_id, "role": "viewer"},
            headers=headers,
        )
        assert first.status_code in [200, 201]

        second = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": other_user_id, "role": "controller"},
            headers=headers,
        )
        assert second.status_code in [200, 201]
        assert second.json().get("role") == "controller"

        listing = client.get(f"/api/v1/devices/{device_id}/access", headers=headers)
        assert listing.status_code == 200
        records = [r for r in listing.json() if r.get("user_id") == other_user_id]
        assert len(records) == 1, f"дубликаты записей: {records}"
        assert records[0]["role"] == "controller"
