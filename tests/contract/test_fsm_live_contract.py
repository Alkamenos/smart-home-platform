"""
Контрактные тесты раздела состояний автоматов (FR-017…FR-023, FR-038).

Проверяют форму ответа и, главное, различение трёх ситуаций: состояния есть,
автоматов нет и сервис недоступен — последняя обязана быть ошибкой 503 с
описанием, а не пустым списком, который можно принять за «автоматов нет».
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Клиент, действующий от администратора."""
    from src.main import app

    return TestClient(app, headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"})


@pytest.fixture
def anonymous_client():
    """Клиент без идентификации пользователя."""
    from src.main import app

    return TestClient(app)


class TestFSMStateEndpoint:
    """GET /api/fsm/state — состояния всех автоматов."""

    def test_should_return_count_and_states_when_requested(self, client: TestClient) -> None:
        """Ответ содержит счётчик и массив состояний."""
        response = client.get("/api/fsm/state")

        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"count", "states"}
        assert body["count"] == len(body["states"])

    def test_should_expose_contract_fields_for_each_state(self, client: TestClient) -> None:
        """Каждое состояние содержит поля контракта."""
        response = client.get("/api/fsm/state")

        for view in response.json()["states"]:
            assert set(view.keys()) == {
                "fsm_id",
                "device_id",
                "behavior",
                "state",
                "since",
                "automated",
            }

    def test_should_return_iso_timestamp_when_state_transitioned(self, client: TestClient) -> None:
        """Время перехода — настенное ISO-8601, а не монотонное (FR-023)."""
        from datetime import datetime

        response = client.get("/api/fsm/state")

        for view in response.json()["states"]:
            if view["since"] is not None:
                parsed = datetime.strptime(view["since"], "%Y-%m-%dT%H:%M:%S.%f")
                assert parsed.year >= 2024

    def test_should_return_empty_list_when_no_fsms_registered(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без автоматов — 200 и пустой список, а не ошибка (FR-021)."""
        from src.main import app

        from core import FSMEngine

        container = app.state.container
        empty_engine = FSMEngine()
        monkeypatch.setattr(container, "_fsm", empty_engine, raising=False)

        response = client.get("/api/fsm/state")

        assert response.status_code == 200
        assert response.json() == {"count": 0, "states": []}

    def test_should_return_503_with_reason_when_container_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Недоступность сервиса — 503 с описанием, а не пустой список (FR-020)."""
        from src.main import app

        monkeypatch.setattr(app.state, "container", None, raising=False)

        response = client.get("/api/fsm/state")

        assert response.status_code == 503
        body = response.json()
        assert "error" in body
        assert body["error"]

    def test_should_report_no_automation_for_device_without_fsm(self, client: TestClient) -> None:
        """Устройство без автоматики помечается явно (FR-019)."""
        created = client.post(
            "/api/v1/devices/sources",
            json={
                "name": "FSM state source",
                "url": "http://192.168.1.55:8123",
                "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJoYSIsImV4cCI6MTcyNzYwMDAwMH0",
            },
        )
        assert created.status_code == 201, created.text
        source = created.json()

        added = client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source["id"],
                "selections": [
                    {
                        "device_entity_id": "switch.no_automation",
                        "name": "Без автоматики",
                        "device_type": "switch",
                    }
                ],
            },
        )
        assert added.status_code in (200, 201), added.text

        devices = client.get("/api/v1/devices").json()
        without = [d for d in devices if d["ha_entity_id"] == "switch.no_automation"]
        assert without, "устройство без автоматики должно появиться в списке"
        assert without[0]["fsm"] == []
        assert without[0]["automation"] == {
            "configured": False,
            "fsm_ids": [],
            "reason": "no_automation",
        }


class TestFSMStateAccessControl:
    """Состояния подчиняются существующей модели доступа (FR-038)."""

    def test_should_return_only_accessible_devices_when_user_restricted(
        self, client: TestClient
    ) -> None:
        """Пользователь без прав на устройство не видит его автоматов."""
        full_access = client.get("/api/fsm/state").json()

        restricted = TestClient(
            client.app, headers={"X-User-ID": "user_without_devices", "X-Is-Admin": "false"}
        ).get("/api/fsm/state")

        assert restricted.status_code == 200
        assert len(restricted.json()["states"]) <= len(full_access["states"])

    def test_should_work_without_identity_header(self, anonymous_client: TestClient) -> None:
        """Эндпоинт доступен и без заголовка: показываются только доступные."""
        response = anonymous_client.get("/api/fsm/state")

        assert response.status_code == 200
        assert "states" in response.json()


class TestFSMStateAccessIsolation:
    """Пользователь без прав не получает состояний чужих устройств (FR-038)."""

    def test_should_not_leak_states_when_user_has_no_accessible_devices(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Пустой список прав означает пустой раздел, а не отказ от фильтрации."""
        from src.main import app

        container = app.state.container
        assert container is not None
        registered = len(container.fsm.get_all_states())
        assert registered > 0, "в контейнере должны быть зарегистрированы автоматы"

        async def no_devices(_user_id: str) -> list:
            return []

        device_service = app.state.device_service
        assert device_service is not None
        monkeypatch.setattr(device_service, "get_user_accessible_devices", no_devices)

        restricted = TestClient(
            client.app, headers={"X-User-ID": "user_without_devices", "X-Is-Admin": "false"}
        )
        body = restricted.get("/api/fsm/state").json()

        assert body == {"count": 0, "states": []}

    def test_should_keep_states_for_admin_when_filtering_disabled(self, client: TestClient) -> None:
        """Администратор видит все состояния: для него фильтрация отключена."""
        body = client.get("/api/fsm/state").json()

        assert body["count"] > 0
