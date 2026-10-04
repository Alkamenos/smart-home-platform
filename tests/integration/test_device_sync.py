"""Интеграционные тесты синхронизации устройств из внешней системы (спека 009).

Проверяют сквозной путь: создание источника → синхронизация → список устройств,
а также отказ при недоступной системе и сохранение данных между перезапусками.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Что изменилось и почему
-----------------------
Три теста этого файла были помечены `@pytest.mark.skip` с причиной «Зависит от
T021-T024 реализации». Причина давно неверна: реализация есть. Фактические
причины, установленные измерением 2026-10-03 и проверкой кода:

- **`POST /sources/{id}/sync` шёл без заголовков и получал 401.**
  `DeviceAccessMiddleware` исключает ровно два случая — `GET /api/v1/devices`
  и `POST /api/v1/devices/sources`. Синхронизация под исключение не попадает.
- **Тест недоступности доходил до сети.** Подменялся `fetch_devices`, но не
  `connect_to_ha`, поэтому код успевал выполнить реальное TCP-соединение.
  Подмена перенесена на шов установки соединения (см. `tests/helpers/ha_stub.py`).
- **`test_sync_persistence` был тавтомологичен.** Он сравнивал длины двух
  пустых списков, а `source_response.json()["id"]` был голым выражением, чьё
  значение отбрасывалось. Проверить сохранение данных он не мог по построению.

Приложение собирается через `create_app` на изолированном хранилище, а не
берётся из синглтона `src.main.app`: тот создаётся при импорте модуля и
замыкает пути данных репозитория до входа в фикстуру.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.helpers.ha_stub import HAUnavailable, stub_ha


def _state(entity_id: str, name: str, value: str = "on", **attributes: object) -> dict:
    """Строит состояние сущности внешней системы.

    Args:
        entity_id: Идентификатор сущности.
        name: Человекочитаемое имя.
        value: Состояние сущности.
        **attributes: Дополнительные атрибуты.

    Returns:
        Состояние в формате Home Assistant.
    """
    return {
        "entity_id": entity_id,
        "state": value,
        "attributes": {"friendly_name": name, **attributes},
    }


class TestSyncFlow:
    """Успешная синхронизация приводит к появлению устройств."""

    def test_sync_creates_devices_from_source(self, isolated_client, ha_states):
        """Синхронизация загружает устройства, и они видны в списке."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={"name": "Sync HA", "url": "http://ha.invalid:8123", "token": "sync_token_12345"},
        )
        assert source.status_code == 201, source.text
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            response = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["device_count"] == 2, f"ожидались 2 устройства: {body}"
        assert body["status"] == "success", f"ожидался статус success: {body}"

        devices = isolated_client.get("/api/v1/devices").json()
        assert len(devices) == 2, f"ожидались 2 устройства в списке: {devices}"

    def test_synced_devices_carry_parsed_attributes(self, isolated_client, ha_states):
        """Атрибуты внешней системы разбираются в поля устройства."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={"name": "Sync HA", "url": "http://ha.invalid:8123", "token": "sync_token_12345"},
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        devices = isolated_client.get("/api/v1/devices").json()
        by_entity = {d["ha_entity_id"]: d for d in devices}

        light = by_entity["light.kitchen"]
        assert light["device_type"] == "light", f"тип не определён: {light}"
        assert light["status"] == "available", f"ожидался статус available: {light}"
        assert light["name"] == "Кухонный свет", f"имя не взято из friendly_name: {light}"

        fan = by_entity["switch.bedroom_fan"]
        assert fan["device_type"] == "switch", f"тип не определён: {fan}"

    def test_sync_is_idempotent(self, isolated_client, ha_states):
        """Повторная синхронизация не создаёт дубли."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={"name": "Sync HA", "url": "http://ha.invalid:8123", "token": "sync_token_12345"},
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            first = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
            second = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert first.json()["device_count"] == 2
        assert second.json()["device_count"] == 2, f"ожидались те же 2 устройства: {second.json()}"

        devices = isolated_client.get("/api/v1/devices").json()
        assert len(devices) == 2, f"ожидались 2 устройства без дублей: {devices}"

    def test_sync_of_empty_source_yields_zero_devices(self, isolated_client):
        """Пустая внешняя система даёт ноль устройств, а не ошибку."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Empty HA",
                "url": "http://ha.invalid:8123",
                "token": "empty_token_12345",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=[]):
            response = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert response.status_code == 200, response.text
        assert response.json()["device_count"] == 0, f"ожидалось 0 устройств: {response.json()}"


class TestSyncFailure:
    """Недоступность внешней системы — штатный проверяемый сценарий."""

    def test_unavailable_source_reports_failure_with_address(self, isolated_client, ha_unavailable):
        """Отказ называет адрес недоступной системы."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            response = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        assert response.status_code == 500, f"ожидался отказ синхронизации: {response.text}"
        detail = response.json()["detail"]
        assert "unreachable.invalid" in detail, f"сообщение должно называть адрес: {detail}"

    def test_failed_sync_keeps_previously_synced_devices(
        self, isolated_client, ha_states, ha_unavailable
    ):
        """Сбой подключения не удаляет ранее загруженные устройства.

        Проверка существенна: потеря данных при недоступности системы — ровно
        тот класс дефекта, ради которого сценарий и выделен отдельно.
        """
        good = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Good HA",
                "url": "http://good.invalid:8123",
                "token": "good_token_12345",
            },
        )
        good_id = good.json()["id"]
        with stub_ha(states=ha_states):
            isolated_client.post(f"/api/v1/devices/sources/{good_id}/sync")

        before = isolated_client.get("/api/v1/devices").json()
        assert len(before) == 2, f"ожидались 2 устройства до сбоя: {before}"

        with stub_ha(mode=HAUnavailable.REFUSED):
            failed = isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        assert failed.status_code == 500
        after = isolated_client.get("/api/v1/devices").json()
        assert len(after) == 2, f"устройства не должны исчезать при сбое: {after}"

    def test_failed_sync_records_reason_on_source(self, isolated_client, ha_unavailable):
        """Причина сбоя сохраняется на источнике, а не теряется."""
        with stub_ha(mode=HAUnavailable.REFUSED):
            isolated_client.post(f"/api/v1/devices/sources/{ha_unavailable}/sync")

        response = isolated_client.get(f"/api/v1/devices/sources/{ha_unavailable}")
        assert response.status_code == 200, response.text
        source = response.json()
        assert source["last_error"], "после сбоя источник обязан хранить причину"
        assert "unreachable.invalid" in source["last_error"], (
            f"причина должна называть адрес: {source['last_error']}"
        )

    def test_successful_sync_clears_previous_error(self, isolated_client, ha_states):
        """Успешная синхронизация снимает прежнюю ошибку источника."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Recovering HA",
                "url": "http://recover.invalid:8123",
                "token": "recover_token_1",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(mode=HAUnavailable.REFUSED):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        with stub_ha(states=ha_states):
            recovered = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert recovered.status_code == 200, recovered.text
        after = isolated_client.get(f"/api/v1/devices/sources/{source_id}").json()
        assert not after["last_error"], f"после успеха ошибка должна быть снята: {after}"

    def test_sync_of_unknown_source_returns_404(self, isolated_client):
        """Синхронизация несуществующего источника — 404, а не 500."""
        from uuid import uuid4

        response = isolated_client.post(f"/api/v1/devices/sources/{uuid4()}/sync")

        assert response.status_code == 404, f"ожидался 404: {response.text}"

    def test_sync_requires_identity(self, isolated_app):
        """Без идентичности синхронизация отклоняется — это ловушка на 401.

        Раньше тест падал здесь, не доходя до своей проверки, и это выглядело
        как «тест красный», а не как «в запросе не хватает заголовка».
        """
        with TestClient(isolated_app) as anonymous:
            source = anonymous.post(
                "/api/v1/devices/sources",
                json={
                    "name": "No Identity HA",
                    "url": "http://ha.invalid:8123",
                    "token": "no_identity_token_1",
                },
            )
            assert source.status_code == 201

            response = anonymous.post(f"/api/v1/devices/sources/{source.json()['id']}/sync")

        assert response.status_code == 401, (
            f"ожидался 401 без идентичности, получен {response.status_code}: {response.text}"
        )


class TestSyncPersistence:
    """Синхронизированные данные переживают перезапуск приложения.

    Каждый тест создаёт собственное приложение через `create_app`, поэтому
    заголовки идентичности передаются явно. Общая фикстура `isolated_client`
    применяет их только к своему экземпляру клиента — пересозданное
    приложение её не использует, и без заголовков запрос к
    `GET /devices/sources` и `POST /sources/{id}/sync` получил бы 401.
    """

    def test_devices_survive_application_restart(self, isolated_workdir, ha_states):
        """Устройства читаются после пересоздания приложения на том же каталоге.

        Прежний тест не пересоздавал приложение вовсе: он делал два чтения подряд
        одним и тем же клиентом и сравнивал длины двух пустых списков. Такая
        проверка не может упасть при любом состоянии кода.
        """
        from webui.app import create_app

        manifest = str(isolated_workdir / "manifest.yaml")
        headers = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}

        with TestClient(create_app(manifest), headers=headers) as first_client:
            source = first_client.post(
                "/api/v1/devices/sources",
                json={
                    "name": "Persistent HA",
                    "url": "http://persist.invalid:8123",
                    "token": "persist_token_12345",
                },
            )
            assert source.status_code == 201, source.text
            source_id = source.json()["id"]

            with stub_ha(states=ha_states):
                sync = first_client.post(f"/api/v1/devices/sources/{source_id}/sync")
            assert sync.status_code == 200, sync.text
            before = first_client.get("/api/v1/devices").json()
            assert len(before) == 2, f"ожидались 2 устройства до перезапуска: {before}"

        # Перезапуск: новое приложение на том же каталоге данных.
        with TestClient(create_app(manifest), headers=headers) as restarted_client:
            after = restarted_client.get("/api/v1/devices").json()

        assert len(after) == 2, f"устройства не пережили перезапуск: {after}"
        assert {d["ha_entity_id"] for d in after} == {"light.kitchen", "switch.bedroom_fan"}, (
            f"состав устройств изменился после перезапуска: {after}"
        )

    def test_source_survives_application_restart(self, isolated_workdir):
        """Источник и его токен переживают перезапуск."""
        from webui.app import create_app

        manifest = str(isolated_workdir / "manifest.yaml")
        headers = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}

        with TestClient(create_app(manifest), headers=headers) as first_client:
            created = first_client.post(
                "/api/v1/devices/sources",
                json={
                    "name": "Surviving HA",
                    "url": "http://survive.invalid:8123",
                    "token": "survive_token_12345",
                },
            )
            assert created.status_code == 201, created.text
            source_id = created.json()["id"]

        with TestClient(create_app(manifest), headers=headers) as restarted_client:
            listed = restarted_client.get("/api/v1/devices/sources")

        assert listed.status_code == 200, listed.text
        sources = listed.json()
        assert len(sources) == 1, f"ожидался ровно один источник: {sources}"
        assert sources[0]["id"] == source_id, f"идентификатор источника изменился: {sources}"

    def test_sync_of_restored_source_keeps_devices_unique(self, isolated_workdir, ha_states):
        """Синхронизация восстановленного источника не плодит дубли.

        Устройства идентифицируются парой (источник, `ha_entity_id`), поэтому
        повторная синхронизация после перезапуска обязана обновить существующие
        записи, а не создать новые.
        """
        from webui.app import create_app

        manifest = str(isolated_workdir / "manifest.yaml")
        headers = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}

        with TestClient(create_app(manifest), headers=headers) as first_client:
            source = first_client.post(
                "/api/v1/devices/sources",
                json={
                    "name": "Restarted HA",
                    "url": "http://restart.invalid:8123",
                    "token": "restart_token_12345",
                },
            )
            source_id = source.json()["id"]
            with stub_ha(states=ha_states):
                first_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        with TestClient(create_app(manifest), headers=headers) as restarted_client:
            with stub_ha(states=ha_states):
                resync = restarted_client.post(f"/api/v1/devices/sources/{source_id}/sync")
            devices = restarted_client.get("/api/v1/devices").json()

        assert resync.status_code == 200, resync.text
        assert resync.json()["device_count"] == 2, f"ожидались 2 устройства: {resync.json()}"
        assert len(devices) == 2, f"ожидались 2 устройства без дублей: {devices}"

    def test_sync_persistence_is_not_tautological(self, isolated_client, ha_states):
        """Страховка от возврата тавтомологичной проверки.

        Настоящий тест переживания перезапуска — `test_devices_survive_application_restart`.
        Здесь фиксируется, что число устройств ненулевое до перезапуска: без
        этого предыдущий тест проходил бы и при полностью пустом хранилище.
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Nonzero HA",
                "url": "http://nonzero.invalid:8123",
                "token": "nonzero_token_1",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        devices = isolated_client.get("/api/v1/devices").json()
        assert len(devices) == 2, (
            f"предусловие не выполнено — тест перезапуска ничего бы не проверял: {devices}"
        )


class TestDeviceRemoval:
    """Исчезновение устройства во внешней системе.

    Ожидаемое поведение задано контрактом `specs/006-device-lifecycle`
    (`contracts/device-lifecycle-api.md:58`) и подтверждено кодом
    (`device_service.py:177-183`): исчезнувшие устройства **не выбрасываются
    из списка**, а помечаются статусом `removed_from_ha` — «молча их не
    теряем». Первая версия этих тестов требовала исчезновения из списка и
    противоречила контракту; проверка исправлена на пометку и снятие
    автоматики.
    """

    def test_vanished_device_is_marked_instead_of_dropped(self, isolated_client, ha_states):
        """Пропавшее устройство помечается `removed_from_ha`, но остаётся видимым."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Vanishing HA",
                "url": "http://vanish.invalid:8123",
                "token": "vanish_token_1",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        assert len(isolated_client.get("/api/v1/devices").json()) == 2

        # Внешняя система больше не отдаёт одно из устройств.
        remaining = [ha_states[0]]
        with stub_ha(states=remaining):
            resync = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert resync.status_code == 200, resync.text
        devices = isolated_client.get("/api/v1/devices").json()
        by_entity = {d["ha_entity_id"]: d for d in devices}

        assert "switch.bedroom_fan" in by_entity, (
            f"пропавшее устройство должно остаться в списке с пометкой: {devices}"
        )
        assert by_entity["switch.bedroom_fan"]["status"] == "removed_from_ha", (
            f"ожидался статус removed_from_ha: {by_entity['switch.bedroom_fan']}"
        )
        assert "light.kitchen" in by_entity, f"существующее устройство потеряно: {devices}"
        assert by_entity["light.kitchen"]["status"] == "available", (
            f"существующее устройство должно остаться доступным: {by_entity['light.kitchen']}"
        )

    def test_vanished_device_has_no_active_automation(self, isolated_client, ha_states):
        """У помеченного устройства снята автоматика.

        Именно это отличает `removed_from_ha` от «просто осталось в списке»:
        устройство не должно продолжать реагировать на события, которых уже
        не будет.
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Vanishing HA",
                "url": "http://vanish.invalid:8123",
                "token": "vanish_token_1",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        with stub_ha(states=[ha_states[0]]):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        devices = isolated_client.get("/api/v1/devices").json()
        by_entity = {d["ha_entity_id"]: d for d in devices}

        vanished = by_entity["switch.bedroom_fan"]
        assert vanished["status"] == "removed_from_ha", f"ожидался removed_from_ha: {vanished}"
        assert not vanished.get("fsm"), (
            f"у помеченного устройства не должно остаться автоматики: {vanished}"
        )

        alive = by_entity["light.kitchen"]
        assert alive["status"] == "available"
        assert alive.get("fsm"), f"у живого устройства автоматика должна сохраниться: {alive}"

    def test_returned_device_gets_its_status_restored(self, isolated_client, ha_states):
        """Вернувшееся устройство восстанавливает статус доступности."""
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Returning HA",
                "url": "http://return.invalid:8123",
                "token": "return_token_123",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        with stub_ha(states=[ha_states[0]]):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        with stub_ha(states=ha_states):
            restored = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert restored.json()["device_count"] == 2, (
            f"ожидалось восстановление обоих: {restored.json()}"
        )
        devices = isolated_client.get("/api/v1/devices").json()
        assert all(d["status"] == "available" for d in devices), (
            f"вернувшееся устройство должно быть доступно: {devices}"
        )
