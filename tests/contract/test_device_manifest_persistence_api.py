"""Сквозная проверка: устройство через HTTP доходит до файла манифеста (#65).

Юнит-тесты `tests/unit/test_device_lifecycle_manifest_persistence.py` собирают
`DeviceLifecycleService` напрямую. Эта проверка идёт по настоящему маршруту
(`POST /api/v1/devices/apply` → `DeviceLifecycleService.add_device`) и убеждается,
что **проводка из приложения не потеряна**: сервис должен получать хранилище
манифеста. Связь исчезнет — юнит-тесты останутся зелёными, потому что собранного
сервиса в них никто не создаёт через `create_app`. Проверено инъекцией: с
убранной передачей `manifest_store` оба теста ниже падают.

Приложение изолированное: операция пишет в манифест, а синглтон `main.app`
собран на манифесте репозитория (`instances/leonids_house/manifest.yaml`), и
правка утекла бы в отслеживаемый файл — ломая `tests/test_bootstrap.py`.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


_SOURCE = {
    "name": "Проверка сохранения",
    "url": "http://192.168.1.7:8123",
    "token": "probe_token_long_enough",
}


def _apply(client: TestClient, source_id: str, entity_id: str, name: str) -> None:
    """Добавляет устройство в комнату `kitchen` через публичный маршрут.

    Args:
        client: HTTP-клиент от имени администратора.
        source_id: Идентификатор источника.
        entity_id: Идентификатор сущности Home Assistant.
        name: Отображаемое имя устройства.
    """
    response = client.post(
        "/api/v1/devices/apply",
        json={
            "source_id": source_id,
            "dry_run": False,
            "selections": [
                {
                    "device_entity_id": entity_id,
                    "device_type": "light",
                    "name": name,
                    "target_room": "kitchen",
                    "behavior_template": "lighting",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["success"] is True, response.json()


def _create_source(client: TestClient, name: str) -> str:
    """Создаёт источник устройств.

    Args:
        client: HTTP-клиент от имени администратора.
        name: Имя источника.

    Returns:
        Идентификатор созданного источника.
    """
    response = client.post(
        "/api/v1/devices/sources",
        json={**_SOURCE, "name": name},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_apply_device_should_reach_manifest_file_when_api_used(
    isolated_workdir: Path,
    isolated_client: TestClient,
) -> None:
    """Добавленное через API устройство появляется в файле манифеста.

    Args:
        isolated_workdir: Временный рабочий каталог с копией манифеста.
        isolated_client: HTTP-клиент от имени администратора.
    """
    _apply(
        isolated_client,
        _create_source(isolated_client, "Проверка сохранения"),
        "light.probe_1",
        "Проба",
    )

    manifest = Path(isolated_workdir) / "manifest.yaml"
    raw = manifest.read_text(encoding="utf-8")
    assert "light.probe_1" in raw, "устройство не записано в файл манифеста"
    assert manifest.with_name("manifest.yaml.bak").exists(), (
        "резервная копия манифеста не создана — запись шла в обход ManifestStore"
    )


def test_delete_device_should_reach_manifest_file_when_api_used(
    isolated_workdir: Path,
    isolated_client: TestClient,
) -> None:
    """Удалённое через API устройство исчезает из файла манифеста.

    Args:
        isolated_workdir: Временный рабочий каталог с копией манифеста.
        isolated_client: HTTP-клиент от имени администратора.
    """
    manifest = Path(isolated_workdir) / "manifest.yaml"
    source_id = _create_source(isolated_client, "Проверка удаления")
    _apply(isolated_client, source_id, "light.probe_delete", "Проба удаления")
    assert "light.probe_delete" in manifest.read_text(encoding="utf-8")

    listing = isolated_client.get("/api/v1/devices?ha_entity_id=light.probe_delete")
    assert listing.status_code == 200, listing.text
    device_id = listing.json()[0]["id"]

    deleted = isolated_client.delete(f"/api/v1/devices/{device_id}")
    assert deleted.status_code == 204, deleted.text

    assert "light.probe_delete" not in manifest.read_text(encoding="utf-8"), (
        "устройство осталось в файле манифеста — вернулось бы при перезапуске"
    )
