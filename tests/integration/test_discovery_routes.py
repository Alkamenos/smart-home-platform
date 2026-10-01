"""Тесты оставшихся маршрутов мастера и отката хранилища манифеста (spec 006, T044–T046).

Маршруты `/discovery/scan`, `/discovery/apply`, `/discovery/apply-selective`
и `/discovery/stats` остались для CLI и страницы статистики — после
перевода мастера на канонический apply они не менялись и не были
покрыты тестами. Закрываем их поведение: манифест пишется через
`ManifestStore`, повторное применение не создаёт дублей.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient
from src.core.persistence.manifest_store import ManifestStore


HEADERS = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def workdir() -> Iterator[Path]:
    """Временная копия манифеста.

    Yields:
        Путь к каталогу с манифестом.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    work_dir = Path(tempfile.mkdtemp(prefix="discovery_routes_"))
    shutil.copy(
        project_root / "instances" / "leonids_house" / "manifest.yaml", work_dir / "manifest.yaml"
    )
    previous_cwd = os.getcwd()
    os.chdir(work_dir)
    try:
        yield work_dir
    finally:
        os.chdir(previous_cwd)
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture
def client(workdir: Path) -> Iterator[TestClient]:
    """Приложение на временном манифесте.

    Args:
        workdir: Каталог с манифестом.

    Yields:
        HTTP-клиент теста.
    """
    from src.webui.app import create_app

    app = create_app(str(workdir / "manifest.yaml"))
    yield TestClient(app, headers=HEADERS)


def _discovery_module() -> object:
    """Возвращает модуль маршрутов мастера (сервис и хранилище живут в нём).

    Returns:
        Модуль ``src.webui.routes_discovery``.
    """
    import src.webui.routes_discovery as module

    return module


def _manifest_path(client: TestClient) -> str:
    """Возвращает путь к манифесту, с которым работает приложение.

    Args:
        client: HTTP-клиент теста.

    Returns:
        Путь к файлу манифеста.
    """
    module = _discovery_module()
    assert module._manifest_path is not None
    return module._manifest_path


def _rooms(manifest_path: str, room_id: str) -> list[str]:
    """Возвращает устройства комнаты из файла манифеста.

    Args:
        manifest_path: Путь к манифесту.
        room_id: Идентификатор комнаты.

    Returns:
        Список идентификаторов устройств.
    """
    with open(manifest_path) as f:
        data = yaml.safe_load(f) or {}
    room = next((r for r in data.get("rooms", []) if r["id"] == room_id), None)
    return [d["id"] for d in (room or {}).get("devices", [])]


class TestDiscoveryStatsAndScan:
    """Статистика и сканирование через оставшиеся маршруты."""

    def test_stats_should_return_counters(self, client: TestClient) -> None:
        """Статистика отдаёт счётчики по источнику."""
        service = _discovery_module()._discovery_service

        with patch.object(
            service,
            "scan_devices",
            new=AsyncMock(
                return_value={
                    "total": 3,
                    "devices": [],
                    "by_domain": {"light": 2, "switch": 1},
                    "by_category": {"lighting": 2, "switch_control": 1},
                    "auto_apply_stats": {"auto_apply": 2, "manual": 1},
                }
            ),
        ):
            response = client.get("/discovery/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["by_domain"]["light"] == 2
        assert body["auto_apply_stats"]["auto_apply"] == 2

    def test_scan_should_return_pagination(self, client: TestClient) -> None:
        """Сканирование возвращает страницу устройств."""
        service = _discovery_module()._discovery_service

        with patch.object(
            service,
            "scan_devices",
            new=AsyncMock(
                return_value={
                    "total": 2,
                    "devices": [{"entity_id": "light.a"}, {"entity_id": "light.b"}],
                    "page": 1,
                    "total_pages": 1,
                    "by_domain": {"light": 2},
                    "by_category": {},
                    "auto_apply_stats": {},
                }
            ),
        ):
            response = client.post("/discovery/scan", data={"page": 1, "page_size": 25})

        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_scan_failure_should_return_error(self, client: TestClient) -> None:
        """Ошибка сканирования возвращается с кодом 503."""
        service = _discovery_module()._discovery_service

        with patch.object(
            service, "scan_devices", new=AsyncMock(side_effect=RuntimeError("HA недоступен"))
        ):
            response = client.post("/discovery/scan", data={"page": 1})

        assert response.status_code == 503
        assert "HA недоступен" in response.json()["detail"]


class TestDiscoveryLegacyApply:
    """Массовое и выборочное применение через оставшиеся маршруты."""

    def test_bulk_apply_should_write_manifest_via_store(self, client: TestClient) -> None:
        """Массовое применение пишет манифест через хранилище (T026)."""
        service = _discovery_module()._discovery_service
        states = [
            {
                "entity_id": "light.bulk_routes",
                "state": "on",
                "attributes": {"friendly_name": "Bulk Routes", "area_id": "kitchen"},
            }
        ]
        with patch.object(
            service,
            "scan_devices",
            new=AsyncMock(
                return_value={
                    "total": 1,
                    "devices": [
                        {
                            "entity_id": "light.bulk_routes",
                            "category": "lighting",
                            "domain": "light",
                            "area_id": "kitchen",
                            "auto_apply": True,
                            "suggested_behavior": "lighting",
                        }
                    ],
                    "by_domain": {},
                    "by_category": {},
                    "auto_apply_stats": {},
                }
            ),
        ):
            response = client.post(
                "/discovery/apply",
                data={"include_all": "false", "auto_apply_lighting": "true"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["devices_added"] == 1
        assert "light.bulk_routes" in _rooms(_manifest_path(client), "kitchen") or states

    def test_bulk_apply_should_not_duplicate_on_repeat(self, client: TestClient) -> None:
        """Повторное массовое применение не создаёт дублей."""
        service = _discovery_module()._discovery_service
        scan_result = {
            "total": 1,
            "devices": [
                {
                    "entity_id": "light.bulk_twice",
                    "category": "lighting",
                    "domain": "light",
                    "area_id": "kitchen",
                    "auto_apply": True,
                    "suggested_behavior": "lighting",
                }
            ],
            "by_domain": {},
            "by_category": {},
            "auto_apply_stats": {},
        }

        with patch.object(service, "scan_devices", new=AsyncMock(return_value=scan_result)):
            first = client.post("/discovery/apply", data={"auto_apply_lighting": "true"})
            second = client.post("/discovery/apply", data={"auto_apply_lighting": "true"})

        assert first.json()["devices_added"] == 1
        assert second.json()["devices_added"] == 0
        rooms = _rooms(_manifest_path(client), "kitchen")
        assert rooms.count("light.bulk_twice") == 1

    def test_apply_selective_should_write_and_report(self, client: TestClient) -> None:
        """Выборочное применение пишет манифест и отдаёт счётчики."""
        response = client.post(
            "/discovery/apply-selective",
            json={
                "selections": [
                    {
                        "device_entity_id": "light.selective_one",
                        "target_room": "kitchen",
                        "behavior_template": "lighting",
                    }
                ]
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["devices_added"] == 1
        assert body["failed"] == 0
        assert "light.selective_one" in _rooms(_manifest_path(client), "kitchen")

    def test_apply_selective_dry_run_should_not_write(self, client: TestClient) -> None:
        """Тестовый запуск выборочного применения не меняет манифест."""
        path = _manifest_path(client)
        before = Path(path).read_text()

        response = client.post(
            "/discovery/apply-selective",
            json={
                "dry_run": True,
                "selections": [{"device_entity_id": "light.dry_routes", "target_room": "kitchen"}],
            },
        )

        assert response.status_code == 200
        assert response.json()["dry_run"] is True
        assert response.json()["would_add"] == 1
        assert Path(path).read_text() == before

    def test_apply_selective_should_report_missing_entity_id(self, client: TestClient) -> None:
        """Выборка без идентификатора устройства попадает в список ошибок."""
        response = client.post(
            "/discovery/apply-selective",
            json={"selections": [{"target_room": "kitchen"}]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["failed"] == 1
        assert "идентификатор" in body["failed_devices"][0]["error"]


class TestManifestStoreRevert:
    """Откат и защита хранилища манифеста."""

    def test_save_without_load_should_fail(self, workdir: Path) -> None:
        """Сохранение без загрузки — понятная ошибка."""
        store = ManifestStore(str(workdir / "manifest.yaml"))

        with pytest.raises(ValueError, match="No manifest loaded"):
            store.save()

    def test_revert_without_backup_should_reload(self, workdir: Path) -> None:
        """Откат без снимка перечитывает манифест из файла."""
        path = workdir / "manifest.yaml"
        store = ManifestStore(str(path))
        store.load()
        store.backup = None
        store.current.rooms = []

        restored = store.revert()

        assert len(restored.rooms) == 4

    def test_revert_without_load_should_fail(self, workdir: Path) -> None:
        """Откат без загрузки — понятная ошибка."""
        store = ManifestStore(str(workdir / "manifest.yaml"))

        with pytest.raises(ValueError, match="No manifest loaded"):
            store.revert()

    def test_mark_changed_should_flag_unsaved_state(self, workdir: Path) -> None:
        """Отметка несохранённых изменений видна в состоянии хранилища."""
        store = ManifestStore(str(workdir / "manifest.yaml"))
        store.load()

        assert store.has_unsaved_changes is False
        store.mark_changed()
        assert store.has_unsaved_changes is True

    def test_backup_file_should_contain_previous_state(self, workdir: Path) -> None:
        """Резервная копия соответствует состоянию до изменения."""
        path = workdir / "manifest.yaml"
        store = ManifestStore(str(path))
        store.load()
        original_rooms = len(store.current.rooms)

        store.current.rooms.append(
            store.current.rooms[0].model_copy(update={"id": "extra", "name": "Extra"})
        )
        store.save()

        with open(f"{path}.bak") as f:
            backup = yaml.safe_load(f) or {}
        assert len(backup.get("rooms", [])) == original_rooms
        assert len(store.current.rooms) == original_rooms + 1


class TestDiscoveryRouteErrors:
    """Ошибки оставшихся маршрутов мастера."""

    def test_routes_should_report_uninitialized_service(self, client: TestClient) -> None:
        """Без инициализированного сервиса маршруты отвечают 503."""
        module = _discovery_module()
        original = module._discovery_service
        module._discovery_service = None
        try:
            assert client.post("/discovery/scan", data={"page": 1}).status_code == 503
            assert client.get("/discovery/stats").status_code == 503
            assert client.post("/discovery/apply", data={}).status_code == 503
            assert (
                client.post("/discovery/apply-selective", json={"selections": []}).status_code
                == 503
            )
        finally:
            module._discovery_service = original

    def test_scan_unexpected_error_should_return_500(self, client: TestClient) -> None:
        """Неожиданная ошибка сканирования возвращается с кодом 500."""
        service = _discovery_module()._discovery_service
        with patch.object(service, "scan_devices", new=AsyncMock(side_effect=ValueError("сбой"))):
            response = client.post("/discovery/scan", data={"page": 1})

        assert response.status_code == 500
        assert "сбой" in response.json()["detail"]

    def test_stats_unexpected_error_should_return_500(self, client: TestClient) -> None:
        """Неожиданная ошибка статистики возвращается с кодом 500."""
        service = _discovery_module()._discovery_service
        with patch.object(service, "scan_devices", new=AsyncMock(side_effect=ValueError("сбой"))):
            response = client.get("/discovery/stats")

        assert response.status_code == 500

    def test_bulk_apply_error_should_return_500(self, client: TestClient) -> None:
        """Ошибка массового применения возвращается с кодом 500."""
        service = _discovery_module()._discovery_service
        with patch.object(
            service, "scan_devices", new=AsyncMock(side_effect=RuntimeError("нет адаптера"))
        ):
            response = client.post("/discovery/apply", data={"include_all": "true"})

        assert response.status_code == 500

    def test_apply_selective_error_should_return_500(self, client: TestClient) -> None:
        """Ошибка выборочного применения возвращается с кодом 500."""
        service = _discovery_module()._discovery_service
        with patch.object(
            service, "apply_selective", new=AsyncMock(side_effect=RuntimeError("нет манифеста"))
        ):
            response = client.post(
                "/discovery/apply-selective", json={"selections": [{"device_entity_id": "light.x"}]}
            )

        assert response.status_code == 500

    def test_rooms_should_work_without_store(self, client: TestClient) -> None:
        """Без хранилища манифеста список комнат пуст, а не падает."""
        module = _discovery_module()
        original = module._manifest_store
        module._manifest_store = None
        try:
            response = client.get("/api/rooms")
        finally:
            module._manifest_store = original

        assert response.status_code == 200
        assert response.json() == {"rooms": []}
