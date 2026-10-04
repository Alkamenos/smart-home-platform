"""
Контрактные тесты для API управления устройствами.

Тесты проверяют контракт между клиентом и сервером для операций над устройствами.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API.

    US4 (spec 004): device-endpoints требуют идентификацию (middleware) —
    клиент по умолчанию действует как администратор (X-User-ID/X-Is-Admin).
    """
    from main import app

    return TestClient(app, headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"})


@pytest.fixture
def sample_source(client):
    """Фикстура для создания тестового источника.

    spec 009 (FR-003, R-6): отсутствие предварительного условия — провал, а не
    повод для пропуска теста. Раньше фикстура молча отдавала ``None`` при любом
    не-201, и девять тестов превращались в no-op вместо падения. Теперь
    неудачная подготовка валит прогон с телом ответа сервера.
    """
    payload = {
        "name": "Test Device Source",
        "url": "http://192.168.1.100:8123",
        "token": "test_device_token",
    }
    response = client.post("/api/v1/devices/sources", json=payload)

    assert response.status_code == 201, (
        f"подготовка не удалась: источник не создан "
        f"(статус={response.status_code}, тело={response.text})"
    )

    source = response.json()
    assert source.get("id"), f"подготовка не удалась: в ответе нет id источника: {source!r}"
    return source


class TestDevicesAPI:
    """Тесты для API управления устройствами."""

    def test_get_devices_empty(self, client):
        """T019: Получение списка устройств (пусто)."""
        response = client.get("/api/v1/devices")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_devices_with_filter_by_source(self, client, sample_source):
        """T019: Получение списка устройств с фильтром по источнику."""
        # Запрашиваем устройства с фильтром
        response = client.get(f"/api/v1/devices?source_id={sample_source['id']}")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_device_by_id_not_found(self, client):
        """T019: Ошибка при получении несуществующего устройства."""
        response = client.get(f"/api/v1/devices/{uuid4()}")

        assert response.status_code == 404

    def test_get_device_by_id_success(self, client, sample_source):
        """T019: Успешное получение информации об устройстве.

        Раньше тест брал фикстуру источника, но не использовал её: подставлял
        случайный ``uuid4()`` — то есть заведомо несуществующее устройство — и
        допускал ``status_code in [200, 404]``. Такой ассерт не мог упасть: для
        случайного id сервер всегда отвечал 404, а 200 был недостижим. Тест
        числился проверкой контракта ``GET /api/v1/devices/{id}`` и не проверял
        ничего.

        Теперь устройство создаётся каноническим путём ``POST
        /api/v1/devices/apply`` от созданного источника, а ответ сверяется точно:
        200 и содержимое именно того устройства, которое создано (Known Issue #35).
        """
        apply_response = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": sample_source["id"],
                "selections": [
                    {
                        "device_entity_id": "light.get_by_id_success",
                        "device_type": "light",
                        "name": "Get By Id Success",
                        "target_room": "living_room",
                        "behaviors": [{"template": "lighting", "priority": 10, "params": {}}],
                    }
                ],
            },
        )
        assert apply_response.status_code == 201, (
            f"подготовка не удалась: устройство не применено (тело={apply_response.text})"
        )
        applied = apply_response.json()["devices"]
        assert len(applied) == 1, (
            f"подготовка не удалась: применено не одно устройство: {applied!r}"
        )
        created = applied[0]

        response = client.get(f"/api/v1/devices/{created['id']}")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["id"] == created["id"], f"ожидалось устройство {created['id']}: {data}"
        assert data["ha_entity_id"] == "light.get_by_id_success", data
        assert data["name"] == "Get By Id Success", data
        assert data["device_type"] == "light", data
        assert data["source_id"] == sample_source["id"], data
        # Ответ устройства обязан совпадать с ответом создания: оба строятся
        # одним _to_device_response, и расхождение означало бы разные контракты.
        assert data == created, f"GET устройства вернул не то, что создал apply:\n{data}\n{created}"


class TestDeviceConfigAPI:
    """Тесты для API конфигурирования устройств (US2 - Фаза 4)."""

    @pytest.fixture
    def sample_device(self, client, sample_source):
        """Фикстура для создания тестового устройства.

        spec 006: устройство кладётся в единый источник — DeviceService,
        который читают роуты (временный словарь роутов удалён).

        spec 009 (FR-003, R-6): подготовка проверяется. Раньше фикстура молча
        отдавала ``None``, и семь тестов ниже превращались в no-op вместо
        падения. Теперь отсутствие источника или устройства валит прогон с
        внятным сообщением.
        """
        assert sample_source.get("id"), (
            f"подготовка не удалась: источник не создан ({sample_source!r})"
        )

        from tests.helpers.device_factory import make_device, seed_device_in_service

        device = make_device(
            ha_entity_id="light.test_light",
            source_id=uuid4(),
            name="Test Light",
            device_type="light",
        )
        seed_device_in_service(client.app.state.device_service, device)

        # Посев обязан быть виден через публичный API: иначе тесты ниже
        # проверяли бы контракт 404 вместо контракта устройства.
        probe = client.get(f"/api/v1/devices/{device.id}")
        assert probe.status_code == 200, (
            f"подготовка не удалась: устройство {device.id} не читается через "
            f"GET /api/v1/devices/{device.id} после посева в DeviceService "
            f"(статус={probe.status_code}, тело={probe.text})"
        )

        return {
            "id": str(device.id),
            "ha_entity_id": device.ha_entity_id,
            "name": device.name,
            "device_type": device.device_type,
            "state": device.state,
            "status": device.status,
        }

    def test_update_device_config_success(self, client, sample_device):
        """T032: Успешное обновление конфигурации устройства."""
        device_id = sample_device["id"]
        payload = {
            "display_name": "Updated Light Name",
            "description": "Updated description",
            "location": "Kitchen",
            "tags": ["important", "lighting"],
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Updated Light Name"
        assert data["description"] == "Updated description"
        assert data["location"] == "Kitchen"
        assert data["tags"] == ["important", "lighting"]

    def test_update_device_config_validation_display_name_empty(self, client, sample_device):
        """T032: Валидация - display_name не может быть пустым."""
        device_id = sample_device["id"]
        payload = {
            "display_name": "",  # Пусто - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_validation_display_name_too_long(self, client, sample_device):
        """T032: Валидация - display_name не может быть > 255 символов."""
        device_id = sample_device["id"]
        payload = {
            "display_name": "x" * 256,  # Слишком длинно - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_validation_description_too_long(self, client, sample_device):
        """T032: Валидация - description не может быть > 1000 символов."""
        device_id = sample_device["id"]
        payload = {
            "description": "x" * 1001,  # Слишком длинно - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_validation_tags_too_many(self, client, sample_device):
        """T032: Валидация - не может быть > 10 тегов."""
        device_id = sample_device["id"]
        payload = {
            "tags": [f"tag_{i}" for i in range(11)]  # 11 тегов - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_not_found(self, client):
        """T032: Ошибка при обновлении конфигурации несуществующего устройства."""
        device_id = uuid4()
        payload = {
            "display_name": "Updated Name",
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 404

    def test_get_device_with_config_success(self, client, sample_device):
        """T033: Получение устройства с полной конфигурацией."""
        device_id = sample_device["id"]

        # Сначала обновляем конфигурацию
        config_payload = {
            "display_name": "Kitchen Light",
            "description": "Main kitchen light",
            "location": "Kitchen",
            "tags": ["lighting", "smart"],
        }
        update_response = client.put(f"/api/v1/devices/{device_id}/config", json=config_payload)
        assert update_response.status_code == 200

        # Теперь получаем устройство с конфигурацией
        response = client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()

        # Проверяем, что конфигурация включена в ответ
        assert "display_name" in data
        assert "description" in data
        assert "location" in data
        assert "tags" in data
        assert data["display_name"] == "Kitchen Light"
        assert data["description"] == "Main kitchen light"
        assert data["location"] == "Kitchen"
        assert data["tags"] == ["lighting", "smart"]

    def test_get_device_with_empty_config(self, client, sample_device):
        """T033: Получение устройства с пустой конфигурацией."""
        device_id = sample_device["id"]
        response = client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()

        # Конфигурационные поля должны быть в ответе
        # (пусто для нового устройства, но они должны быть)
        assert "display_name" in data or "config" in data
        assert "id" in data
        assert "ha_entity_id" in data

    def test_execute_command_validation(self, client):
        """T044: Валидация параметров команды."""
        device_id = uuid4()

        # Отправляем команду с неправильным форматом
        payload = {
            "name": "turn_on",
            # Отсутствует обязательный параметр
        }

        response = client.post(f"/api/v1/devices/{device_id}/command", json=payload)

        # Должна быть ошибка валидации
        assert response.status_code in [400, 422]

    def test_execute_command_device_not_found(self, client):
        """T044: Ошибка при отправке команды для несуществующего устройства."""
        device_id = uuid4()

        payload = {
            "name": "turn_on",
            "parameters": {},
        }

        response = client.post(f"/api/v1/devices/{device_id}/command", json=payload)

        # Должна быть ошибка 404
        assert response.status_code == 404

    def test_execute_command_response_format(self, client):
        """T044: Ответ команды содержит поля контракта.

        Раньше тело теста было `pass` — он проходил, ничего не проверяя, и
        числился покрытием формата ответа. Теперь контракт проверяется на
        существующем устройстве с реальными правами: отсутствие нужного поля
        должно приводить к отказу.
        """
        from tests.helpers.device_factory import make_device, seed_device_in_service

        device = make_device(ha_entity_id="light.response_format", name="Формат ответа")
        seed_device_in_service(client.app.state.device_service, device)

        grant = client.post(
            f"/api/v1/devices/{device.id}/access",
            json={"user_id": "response_format_user", "role": "controller"},
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        assert grant.status_code in (200, 201), grant.text

        response = client.post(
            f"/api/v1/devices/{device.id}/command",
            json={"command_name": "turn_on"},
            headers={"X-User-ID": "response_format_user"},
        )
        assert response.status_code == 202, response.text

        body = response.json()
        for field in ("id", "device_id", "command_name", "status", "created_at"):
            assert field in body, f"в ответе команды нет поля {field}: {body}"
        assert body["status"] == "executing", f"ожидался статус executing: {body}"
        assert body["command_name"] == "turn_on"
        assert body["device_id"] == str(device.id)

    def test_get_device_events(self, client):
        """T045: GET /api/v1/devices/{id}/events возвращает историю событий."""
        device_id = uuid4()

        response = client.get(f"/api/v1/devices/{device_id}/events")

        # Должен вернуть 200 или 404
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            # Должен быть список событий
            assert isinstance(data, list)

    def test_get_device_events_with_filter(self, client):
        """T045: GET /api/v1/devices/{id}/events с фильтром по типу."""
        device_id = uuid4()

        response = client.get(f"/api/v1/devices/{device_id}/events?event_type=state_changed")

        assert response.status_code in [200, 404]


class TestDeviceDeleteAPI:
    """T037: контракт удаления устройства (spec 006, US4, FR-024–FR-027)."""

    @staticmethod
    def _applied_device(client, source_id: str) -> dict:
        """Добавляет устройство через канонический apply и возвращает его.

        Args:
            client: HTTP-клиент теста.
            source_id: Идентификатор источника.

        Returns:
            Описание добавленного устройства из списка.
        """
        response = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source_id,
                "selections": [
                    {
                        "device_entity_id": "light.contract_delete",
                        "device_type": "light",
                        "name": "Contract Delete",
                        "target_room": "living_room",
                        "behaviors": [{"template": "lighting", "priority": 10, "params": {}}],
                    }
                ],
            },
        )
        assert response.status_code == 201
        devices = client.get("/api/v1/devices").json()
        return next(d for d in devices if d["ha_entity_id"] == "light.contract_delete")

    def test_delete_should_return_204(self, client, sample_source):
        """Удаление существующего устройства — 204 без тела."""
        device = self._applied_device(client, sample_source["id"])

        response = client.delete(f"/api/v1/devices/{device['id']}")

        assert response.status_code == 204
        assert response.content == b""

    def test_delete_should_remove_device_from_list(self, client, sample_source):
        """После удаления устройства нет ни в списке, ни в ответе устройства."""
        device = self._applied_device(client, sample_source["id"])

        client.delete(f"/api/v1/devices/{device['id']}")

        assert device["id"] not in [d["id"] for d in client.get("/api/v1/devices").json()]
        assert client.get(f"/api/v1/devices/{device['id']}").status_code == 404

    def test_repeated_delete_should_stay_successful(self, client, sample_source):
        """Повторное удаление — тоже успех (идемпотентность, FR-027)."""
        device = self._applied_device(client, sample_source["id"])

        first = client.delete(f"/api/v1/devices/{device['id']}")
        second = client.delete(f"/api/v1/devices/{device['id']}")

        assert first.status_code == 204
        assert second.status_code == 204

    def test_delete_should_require_admin(self, client, sample_source):
        """Без прав администратора удаление запрещено (FR-026)."""
        device = self._applied_device(client, sample_source["id"])

        response = client.delete(
            f"/api/v1/devices/{device['id']}",
            headers={"X-User-ID": "plain_user", "X-Is-Admin": "false"},
        )

        assert response.status_code == 403
        assert device["id"] in [d["id"] for d in client.get("/api/v1/devices").json()]

    def test_delete_should_require_identification(self, client, sample_source):
        """Без идентификации запрос отклоняется защитным слоем."""
        device = self._applied_device(client, sample_source["id"])

        response = client.delete(f"/api/v1/devices/{device['id']}", headers={"X-User-ID": ""})

        assert response.status_code in (401, 403)

    def test_delete_unknown_device_should_return_404(self, client):
        """Удаление несуществующего устройства — 404."""
        response = client.delete(f"/api/v1/devices/{uuid4()}")

        assert response.status_code == 404
