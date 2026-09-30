"""Контрактные тесты истории операций устройства (spec 005, ТР-010, T007).

Контракт: GET /api/v1/devices/{device_id}/events — contracts/device-events-api.md
"""

import asyncio
import contextlib
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app

    return TestClient(app)


@pytest.fixture
def admin_user_id():
    """Администратор (для grant роли и операций)."""
    return "admin_event_user"


@pytest.fixture
def viewer_user_id():
    """Пользователь с ролью viewer на устройство."""
    return "viewer_event_user"


@pytest.fixture
def sample_device():
    """Устройство, добавленное напрямую в хранилище (паттерн test_devices_api)."""
    from datetime import datetime as dt

    from webui.routes.devices.devices import _devices_store

    device_id = str(uuid4())
    _devices_store[device_id] = {
        "id": device_id,
        "ha_entity_id": "light.test_events",
        "source_id": str(uuid4()),
        "name": "Events Test Device",
        "device_type": "light",
        "state": {"state": "on"},
        "status": "available",
        "created_at": dt.utcnow().isoformat(),
        "updated_at": dt.utcnow().isoformat(),
    }
    return device_id


@pytest.fixture
def viewer_access(client, sample_device, admin_user_id, viewer_user_id):
    """Роль viewer для viewer_user_id на test-устройство.

    Роль — окружение теста, а не операция над устройством: запись
    доступа создаётся напрямую в persistence, чтобы не засорять историю
    операций (spec 005) записью grant'а.
    """
    from uuid import UUID as _UUID

    from src.core.models.device_access import DeviceAccess
    from src.main import app

    access = DeviceAccess(
        device_id=_UUID(sample_device),
        user_id=viewer_user_id,
        role="viewer",
        granted_by=admin_user_id,
    )
    persistence = app.state.persistence.device_access
    asyncio.run(persistence.save_access(access))

    yield access

    with contextlib.suppress(Exception):
        asyncio.run(persistence.delete_access(access.id))


@pytest.fixture
def recorded_events(client, sample_device, admin_user_id):
    """Добавляет записи истории напрямую через persistence приложения.

    Независимость от US2/US3: чтение проверяется без выполнения операций
    через API. Очистка — в teardown (удаление своих записей из файла).
    """
    from src.main import app

    persistence = app.state.persistence.device_sync_events
    events = [
        {
            "id": uuid4(),
            "device_id": sample_device,
            "action": "config_changed",
            "user_id": admin_user_id,
            "timestamp": datetime(2026, 9, 29, 12, 0, 0),
            "before": {"location": "кухня"},
            "after": {"location": "гостиная"},
        },
        {
            "id": uuid4(),
            "device_id": sample_device,
            "action": "command_executed",
            "user_id": "operator",
            "timestamp": datetime(2026, 9, 29, 12, 5, 0),
            "before": None,
            "after": None,
            "data": {"command": "turn_on"},
        },
    ]

    from src.core.models.device_sync_event import DeviceSyncEvent

    created = [DeviceSyncEvent(**e) for e in events]
    for event in created:
        asyncio.run(persistence.append_event(event))

    yield created

    # Teardown: убрать тестовые записи из общего файла истории
    try:
        import json

        with open(persistence.events_file) as f:
            data = json.load(f)
        for event in created:
            data.pop(str(event.id), None)
        with open(persistence.events_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except FileNotFoundError:
        pass


def _auth(user_id: str) -> dict[str, str]:
    """Заголовки идентификации пользователя."""
    return {"X-User-ID": user_id}


class TestGetDeviceEventsHistory:
    """Контрактные кейсы 1, 5, 9 — содержимое и пустой список."""

    def test_no_operations_returns_empty_list(
        self, client, sample_device, viewer_access, viewer_user_id
    ):
        """Кейс 5: устройство без операций → 200 и пустой список."""
        response = client.get(
            f"/api/v1/devices/{sample_device}/events",
            headers=_auth(viewer_user_id),
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_returns_recorded_operations(
        self, client, sample_device, viewer_access, viewer_user_id, recorded_events
    ):
        """Кейс 1 (SC-001/SC-004): записи операций отдаются с полями контракта."""
        response = client.get(
            f"/api/v1/devices/{sample_device}/events",
            headers=_auth(viewer_user_id),
        )

        assert response.status_code == 200
        records = response.json()
        assert len(records) == 2

        # Новые первыми
        assert records[0]["event_type"] == "command_executed"
        assert records[0]["data"]["user_id"] == "operator"
        assert records[0]["data"]["before"] is None
        assert records[0]["data"]["after"] is None
        assert records[0]["data"]["command"] == "turn_on"

        config_record = records[1]
        assert config_record["event_type"] == "config_changed"
        assert config_record["data"]["user_id"] == "admin_event_user"
        assert config_record["data"]["before"] == {"location": "кухня"}
        assert config_record["data"]["after"] == {"location": "гостиная"}
        assert config_record["device_id"] == sample_device
        assert isinstance(config_record["timestamp"], str)

    def test_unknown_event_type_returns_empty(
        self, client, sample_device, viewer_access, viewer_user_id, recorded_events
    ):
        """Кейс 9: неизвестное значение фильтра → 200 и пустой список."""
        response = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=nonexistent",
            headers=_auth(viewer_user_id),
        )

        assert response.status_code == 200
        assert response.json() == []


class TestFilteringAndPagination:
    """Контрактные кейсы 2–3 — фильтр и пагинация (FR-007)."""

    def test_filter_by_event_type(
        self, client, sample_device, viewer_access, viewer_user_id, recorded_events
    ):
        """Фильтр возвращает только операции выбранного типа."""
        response = client.get(
            f"/api/v1/devices/{sample_device}/events?event_type=config_changed",
            headers=_auth(viewer_user_id),
        )

        assert response.status_code == 200
        records = response.json()
        assert len(records) == 1
        assert records[0]["event_type"] == "config_changed"

    def test_pagination(
        self, client, sample_device, viewer_access, viewer_user_id, recorded_events
    ):
        """limit/offset отдают вторую запись (новые первыми)."""
        response = client.get(
            f"/api/v1/devices/{sample_device}/events?limit=1&offset=1",
            headers=_auth(viewer_user_id),
        )

        assert response.status_code == 200
        records = response.json()
        assert len(records) == 1
        assert records[0]["event_type"] == "config_changed"


class TestAccessDenied:
    """Контрактные кейсы 6–8 — отказы (FR-008, spec 004)."""

    def test_unknown_device_returns_404(self, client, viewer_user_id):
        """Кейс 6: устройство не существует → 404 (existence раньше доступа)."""
        response = client.get(
            f"/api/v1/devices/{uuid4()}/events",
            headers=_auth(viewer_user_id),
        )

        assert response.status_code == 404

    def test_without_role_returns_403(self, client, sample_device):
        """Кейс 7: идентифицированный без роли viewer → 403."""
        response = client.get(
            f"/api/v1/devices/{sample_device}/events",
            headers=_auth("user_without_any_role"),
        )

        assert response.status_code == 403

    def test_without_identification_returns_401(self, client, sample_device):
        """Кейс 8: без заголовков идентификации → 401 (middleware spec 004)."""
        response = client.get(f"/api/v1/devices/{sample_device}/events")

        assert response.status_code == 401
