"""Интеграционные тесты истории операций устройств (spec 005, ТР-010, T008).

Сценарии quickstart: 1 (конфигурация), 4 (перезапуск), 6 (отказ записи).
"""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app

    return TestClient(app)


@pytest.fixture
def admin_user_id():
    """Администратор — инициатор операций."""
    return "admin_audit_user"


@pytest.fixture
def sample_device(client):
    """Устройство, посеянное в единый источник (DeviceService) — spec 006."""
    from tests.helpers.device_factory import make_device, seed_device_in_service

    device = make_device(ha_entity_id="light.test_audit", name="Audit Test Device")
    seed_device_in_service(client.app.state.device_service, device)
    return str(device.id)


@pytest.fixture
def admin_access(client, sample_device, admin_user_id):
    """Роль admin для admin_user_id на test-устройство."""
    response = client.post(
        f"/api/v1/devices/{sample_device}/access",
        json={"user_id": admin_user_id, "role": "admin"},
        headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
    )
    assert response.status_code in (200, 201), response.text


@pytest.fixture
def cleanup_history():
    """Очистка тестовых записей истории из общего data-файла (teardown)."""
    created_device_ids: list[str] = []
    yield created_device_ids

    from src.main import app

    persistence = app.state.persistence.device_sync_events
    if not persistence.events_file.exists():
        return
    try:
        with open(persistence.events_file) as f:
            data = json.load(f)
        remaining = {
            key: record
            for key, record in data.items()
            if record.get("device_id") not in created_device_ids
        }
        with open(persistence.events_file, "w") as f:
            json.dump(remaining, f, indent=2, default=str)
    except (json.JSONDecodeError, FileNotFoundError):
        pass


class TestConfigChangeRecorded:
    """Сценарий 1 (SC-001, FR-001, FR-003): операция конфигурации в истории."""

    def test_config_update_creates_history_record(
        self, client, sample_device, admin_access, admin_user_id, cleanup_history
    ):
        """PUT config → запись config_changed с инициатором и before/after."""
        cleanup_history.append(sample_device)

        put_response = client.put(
            f"/api/v1/devices/{sample_device}/config",
            json={"location": "гостиная"},
            headers={"X-User-ID": admin_user_id},
        )
        assert put_response.status_code == 200, put_response.text

        events_response = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=config_changed",
            headers={"X-User-ID": admin_user_id},
        )
        assert events_response.status_code == 200
        records = events_response.json()

        assert len(records) == 1, f"Ожидалась 1 запись, получено: {records}"
        record = records[0]
        assert record["device_id"] == sample_device
        assert record["data"]["user_id"] == admin_user_id
        assert record["data"]["after"] == {"location": "гостиная"}
        # before — состояние до операции (config только создавался)
        assert isinstance(record["data"]["before"], dict)

    def test_config_update_success_even_if_history_unavailable(
        self, client, sample_device, admin_access, admin_user_id
    ):
        """Сценарий 6 (FR-009): недоступная история не фейлит операцию."""
        from src.main import app

        saved_persistence = app.state.persistence
        try:
            app.state.persistence = None

            response = client.put(
                f"/api/v1/devices/{sample_device}/config",
                json={"description": "описание при недоступной истории"},
                headers={"X-User-ID": admin_user_id},
            )

            assert response.status_code == 200, response.text
        finally:
            app.state.persistence = saved_persistence


class TestHistorySurvivesRestart:
    """Сценарий 4 (SC-003, FR-002): история переживает перезапуск."""

    def test_records_survive_app_restart(
        self, client, sample_device, admin_access, admin_user_id, cleanup_history
    ):
        """Запись создаётся → приложение пересоздано → запись читается."""
        cleanup_history.append(sample_device)

        put_response = client.put(
            f"/api/v1/devices/{sample_device}/config",
            json={"location": "спальня"},
            headers={"X-User-ID": admin_user_id},
        )
        assert put_response.status_code == 200, put_response.text

        # «Рестарт»: полностью новое приложение на том же data-каталоге
        from src.webui.app import create_app

        restarted_client = TestClient(create_app())
        events_response = restarted_client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=config_changed",
            headers={"X-User-ID": admin_user_id},
        )

        assert events_response.status_code == 200
        records = events_response.json()
        assert len(records) == 1, f"Запись потеряна после рестарта: {records}"
        assert records[0]["event_type"] == "config_changed"
        assert records[0]["data"]["after"] == {"location": "спальня"}


class TestAccessHistory:
    """Сценарий 2 (SC-002, FR-004): операции прав доступа в истории."""

    def test_grant_update_and_revoke_recorded(
        self, client, sample_device, admin_access, admin_user_id, cleanup_history
    ):
        """Выдача, обновление роли и отзыв создают записи с инициатором."""
        cleanup_history.append(sample_device)
        target_user = "target_access_user"
        auth = {"X-User-ID": admin_user_id, "X-Is-Admin": "true"}

        # Выдача
        grant1 = client.post(
            f"/api/v1/devices/{sample_device}/access",
            json={"user_id": target_user, "role": "viewer"},
            headers=auth,
        )
        assert grant1.status_code in (200, 201), grant1.text

        events = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=access_granted",
            headers={"X-User-ID": admin_user_id},
        ).json()
        # fixture admin_access тоже создаёт grant — фильтруем по получателю
        granted = [e for e in events if e["data"].get("granted_to") == target_user]
        assert len(granted) == 1, f"Ожидалась запись access_granted: {events}"
        assert granted[0]["data"]["user_id"] == admin_user_id
        assert granted[0]["data"]["after"] == {"role": "viewer"}

        # Обновление роли (повторный grant)
        grant2 = client.post(
            f"/api/v1/devices/{sample_device}/access",
            json={"user_id": target_user, "role": "controller"},
            headers=auth,
        )
        assert grant2.status_code in (200, 201), grant2.text
        # Повторный grant заменяет запись доступа — отзыв по актуальному id
        access_id = grant2.json()["id"]

        updated_events = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=access_updated",
            headers={"X-User-ID": admin_user_id},
        ).json()
        updated = [e for e in updated_events if e["data"].get("granted_to") == target_user]
        assert len(updated) == 1, f"Ожидалась запись access_updated: {updated_events}"
        assert updated[0]["data"]["before"] == {"role": "viewer"}
        assert updated[0]["data"]["after"] == {"role": "controller"}

        # Отзыв
        revoke = client.delete(
            f"/api/v1/devices/{sample_device}/access/{access_id}",
            headers=auth,
        )
        assert revoke.status_code == 204, revoke.text

        revoked_events = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=access_revoked",
            headers={"X-User-ID": admin_user_id},
        ).json()
        revoked = [e for e in revoked_events if e["data"].get("granted_to") == target_user]
        assert len(revoked) == 1, f"Ожидалась запись access_revoked: {revoked_events}"
        assert revoked[0]["data"]["user_id"] == admin_user_id
        assert revoked[0]["data"]["before"] == {"role": "controller"}
        assert revoked[0]["data"]["after"] is None


class TestCommandHistory:
    """Сценарий 3 (SC-001, FR-005): отправленные команды в истории."""

    def test_command_creates_history_record(
        self, client, sample_device, admin_access, admin_user_id, cleanup_history
    ):
        """POST /command → запись command_executed с данными команды, до/после пустые."""
        cleanup_history.append(sample_device)

        command_response = client.post(
            f"/api/v1/devices/{sample_device}/command",
            json={"name": "turn_on", "parameters": {"brightness": 80}},
            headers={"X-User-ID": admin_user_id},
        )
        assert command_response.status_code == 202, command_response.text

        events = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=command_executed",
            headers={"X-User-ID": admin_user_id},
        ).json()

        assert len(events) == 1, f"Ожидалась запись command_executed: {events}"
        record = events[0]
        assert record["data"]["user_id"] == admin_user_id
        assert record["data"]["command"] == "turn_on"
        assert record["data"]["before"] is None
        assert record["data"]["after"] is None
