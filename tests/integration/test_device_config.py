"""Интеграционные тесты конфигурации устройств (спека 009, T007).

Проверяют редактирование пользовательской конфигурации устройства: полный
поток, частичное обновление, валидацию и ограничения доступа.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Что изменилось и почему
-----------------------
Три теста этого файла были помечены `@pytest.mark.skip` с причиной «Зависит от
T032-T033 реализации». Реализация есть; фактическая причина падения —
`DeviceAccessMiddleware` отклоняет с 401 любой запрос под `/api/v1/devices/**`,
кроме ровно двух исключений, а **все** запросы этого файла шли без заголовков.

Особенно важно для `test_config_validation_error_handling`: раньше он
останавливался на 401 первого же запроса, то есть валидацию **не проверял вовсе**,
хотя числился её проверкой.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.helpers.ha_stub import stub_ha


@pytest.fixture
def configured_device(isolated_client, ha_states):
    """Устройство, полученное настоящей синхронизацией источника.

    Посев в память не годился бы: конфигурация проверяется и на диске, поэтому
    устройство обязано пройти полный путь от HTTP-запроса до персистентности.

    Args:
        isolated_client: HTTP-клиент теста.
        ha_states: Состояния внешней системы.

    Returns:
        Идентификатор устройства.
    """
    source = isolated_client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Config HA",
            "url": "http://config.invalid:8123",
            "token": "config_token_12345",
        },
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    with stub_ha(states=ha_states):
        sync = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
    assert sync.status_code == 200, sync.text

    devices = isolated_client.get("/api/v1/devices").json()
    assert devices, "синхронизация не создала ни одного устройства"
    return str(devices[0]["id"])


class TestFullConfigEditFlow:
    """Полное редактирование конфигурации."""

    def test_all_fields_are_applied(self, isolated_client, configured_device):
        """Все поля конфигурации применяются и возвращаются в ответе."""
        payload = {
            "display_name": "Кухонный свет",
            "description": "Основное освещение кухни",
            "location": "Кухня",
            "tags": ["lighting", "kitchen", "smart"],
        }

        response = isolated_client.put(f"/api/v1/devices/{configured_device}/config", json=payload)

        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["display_name"] == "Кухонный свет", f"поля не применены: {updated}"
        assert updated["description"] == "Основное освещение кухни"
        assert updated["location"] == "Кухня"
        assert updated["tags"] == ["lighting", "kitchen", "smart"]

    def test_config_survives_restart(self, isolated_workdir, ha_states):
        """Конфигурация переживает перезапуск приложения.

        Прежний тест делал второй `GET` **тем же** клиентом и называл это
        «имитацией перезагрузки». Это не перезагрузка: тот же экземпляр сервиса
        отдаёт то, что только что записал в память. Настоящая перезагрузка —
        новое приложение на том же каталоге данных.
        """
        from webui.app import create_app

        manifest = str(isolated_workdir / "manifest.yaml")
        headers = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}

        with TestClient(create_app(manifest), headers=headers) as first_client:
            source = first_client.post(
                "/api/v1/devices/sources",
                json={
                    "name": "Restart HA",
                    "url": "http://restart.invalid:8123",
                    "token": "restart_token_12345",
                },
            )
            source_id = source.json()["id"]
            with stub_ha(states=ha_states):
                first_client.post(f"/api/v1/devices/sources/{source_id}/sync")

            device_id = first_client.get("/api/v1/devices").json()[0]["id"]
            updated = first_client.put(
                f"/api/v1/devices/{device_id}/config",
                json={"display_name": "Кухонный свет", "location": "Кухня"},
            )
            assert updated.status_code == 200, updated.text

        with TestClient(create_app(manifest), headers=headers) as restarted_client:
            reloaded = restarted_client.get(f"/api/v1/devices/{device_id}")

        assert reloaded.status_code == 200, reloaded.text
        device = reloaded.json()
        assert device["display_name"] == "Кухонный свет", (
            f"конфигурация не пережила перезапуск: {device}"
        )
        assert device["location"] == "Кухня"

    def test_config_change_is_recorded_in_history(self, isolated_client, configured_device):
        """Изменение конфигурации попадает в историю устройства.

        Без этой проверки тест проходил бы и при молчаливой потере истории —
        то есть при самом тихом виде отказа.
        """
        before = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config", json={"location": "Кухня"}
        )
        assert before.status_code == 200, before.text

        events = isolated_client.get(
            f"/api/v1/devices/{configured_device}/events?event_type=config_changed"
        )

        assert events.status_code == 200, events.text
        records = events.json()
        assert len(records) == 1, f"ожидалась одна запись об изменении: {records}"
        assert records[0]["event_type"] == "config_changed"
        assert records[0]["data"]["after"]["location"] == "Кухня"

    def test_config_change_preserves_untouched_fields(self, isolated_client, configured_device):
        """Частичное обновление не затирает остальные поля."""
        first = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={
                "display_name": "Test Light",
                "description": "Test Description",
                "location": "Test Location",
                "tags": ["test"],
            },
        )
        assert first.status_code == 200, first.text

        partial = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config", json={"display_name": "Updated Light"}
        )

        assert partial.status_code == 200, partial.text
        updated = partial.json()
        assert updated["display_name"] == "Updated Light", f"поле не изменилось: {updated}"
        assert updated["description"] == "Test Description", f"описание затёрто: {updated}"
        assert updated["location"] == "Test Location", f"расположение затёрто: {updated}"
        assert updated["tags"] == ["test"], f"теги затёрты: {updated}"


class TestConfigValidation:
    """Валидация конфигурации."""

    def test_display_name_too_long_is_rejected(self, isolated_client, configured_device):
        """Слишком длинное имя отклоняется — и запрос доходит до валидации.

        Проверка начинается с кода ответа 422, а не 401: это гарантирует, что
        запрос действительно дошёл до валидации, а не отскочил на middleware.
        """
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={"display_name": "x" * 256},
        )

        assert response.status_code == 422, (
            f"ожидался 422 от валидации, получен {response.status_code}: {response.text}"
        )

    def test_empty_display_name_is_rejected(self, isolated_client, configured_device):
        """Пустое имя отклоняется."""
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config", json={"display_name": ""}
        )

        assert response.status_code == 422, f"ожидался 422: {response.text}"

    def test_too_many_tags_are_rejected(self, isolated_client, configured_device):
        """Более десяти тегов отклоняется."""
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={"tags": [f"tag_{n}" for n in range(11)]},
        )

        assert response.status_code in (400, 422), (
            f"ожидался отказ по числу тегов, получен {response.status_code}: {response.text}"
        )

    def test_too_long_tag_is_rejected(self, isolated_client, configured_device):
        """Тег длиннее пятидесяти символов отклоняется."""
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={"tags": ["x" * 51]},
        )

        assert response.status_code in (400, 422), (
            f"ожидался отказ по длине тега, получен {response.status_code}: {response.text}"
        )

    def test_too_long_description_is_rejected(self, isolated_client, configured_device):
        """Описание длиннее тысячи символов отклоняется."""
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={"description": "x" * 1001},
        )

        assert response.status_code == 422, f"ожидался 422: {response.text}"

    def test_boundary_lengths_are_accepted(self, isolated_client, configured_device):
        """Граничные длины принимаются — иначе проверка отказа была бы ложной.

        Без этого теста «слишком длинное отклоняется» проходило бы и при
        произвольной границе, то есть проверяло бы не правило, а факт отказа.
        """
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={"display_name": "x" * 255, "description": "y" * 1000, "tags": ["z" * 50]},
        )

        assert response.status_code == 200, (
            f"граничные значения обязаны приниматься: {response.text}"
        )

    def test_ten_tags_are_accepted(self, isolated_client, configured_device):
        """Ровно десять тегов допустимо."""
        response = isolated_client.put(
            f"/api/v1/devices/{configured_device}/config",
            json={"tags": [f"tag_{n}" for n in range(10)]},
        )

        assert response.status_code == 200, f"десять тегов обязаны приниматься: {response.text}"


class TestConfigAccessControl:
    """Изменение конфигурации требует административной роли."""

    def test_reviewer_cannot_change_config(self, isolated_client, configured_device, grant_viewer):
        """Пользователь с ролью только для чтения не меняет конфигурацию.

        Args:
            isolated_client: HTTP-клиент теста.
            configured_device: Идентификатор устройства.
            grant_viewer: Идентификатор записи о доступе.
        """
        with TestClient(isolated_client.app, headers={"X-User-ID": "user_viewer"}) as reviewer:
            response = reviewer.put(
                f"/api/v1/devices/{configured_device}/config", json={"location": "Кухня"}
            )

        assert response.status_code == 403, (
            f"ожидался 403 для роли viewer, получен {response.status_code}: {response.text}"
        )

    def test_user_without_rights_cannot_change_config(self, isolated_client, configured_device):
        """Пользователь без записи о доступе не меняет конфигурацию."""
        with TestClient(
            isolated_client.app, headers={"X-User-ID": "user_without_rights"}
        ) as stranger:
            response = stranger.put(
                f"/api/v1/devices/{configured_device}/config", json={"location": "Кухня"}
            )

        assert response.status_code == 403, (
            f"ожидался 403, получен {response.status_code}: {response.text}"
        )

    def test_request_without_identity_is_rejected(self, isolated_app, configured_device):
        """Без идентичности запрос отклоняется с 401.

        Контраст с соседним тестом существенен: без идентичности отказ приходит
        на 401 от middleware, а с идентичностью и недостаточной ролью — 403 от
        роута. Разные коды означают разные причины, и их смешивать нельзя.
        """
        with TestClient(isolated_app) as anonymous:
            response = anonymous.put(
                f"/api/v1/devices/{configured_device}/config", json={"location": "Кухня"}
            )

        assert response.status_code == 401, f"ожидался 401: {response.text}"
        assert response.json()["detail"] == "Missing X-User-ID header"

    def test_config_of_unknown_device_returns_404(self, isolated_client):
        """Конфигурация несуществующего устройства — 404."""
        from uuid import uuid4

        response = isolated_client.put(
            f"/api/v1/devices/{uuid4()}/config", json={"location": "Кухня"}
        )

        assert response.status_code == 404, f"ожидался 404: {response.text}"

    def test_rejected_config_leaves_device_unchanged(
        self, isolated_client, configured_device, grant_viewer
    ):
        """Отклонённое изменение не применяется частично.

        Проверка существенна: без неё тест на права проходил бы и при записи
        конфигурации до проверки прав — то есть при утечке изменения.
        """
        before = isolated_client.get(f"/api/v1/devices/{configured_device}").json()
        original_location = before.get("location")

        with TestClient(isolated_client.app, headers={"X-User-ID": "user_viewer"}) as reviewer:
            reviewer.put(
                f"/api/v1/devices/{configured_device}/config", json={"location": "Взломано"}
            )

        after = isolated_client.get(f"/api/v1/devices/{configured_device}").json()
        assert after.get("location") == original_location, (
            f"отклонённое изменение было применено: {after}"
        )
