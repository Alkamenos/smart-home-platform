"""Интеграционные тесты управления доступом к устройствам (спека 009, T008).

Проверяют полный сценарий: назначение прав → видимость устройства → команды →
повышение роли → отзыв доступа. Это единственный в проекте сквозной тест,
проходящий весь путь от источника до команд и прав.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Что изменилось и почему
-----------------------
Три теста этого файла были помечены `@pytest.mark.skip` с причиной «Зависит от
T064-T067 реализации». Реализация есть; фактические причины были другими:

- **`test_full_access_control_flow` доходил до сети.** Подменялся
  `fetch_devices`, но не `connect_to_ha`, поэтому код успевал выполнить
  реальное соединение с `192.168.1.100:8123`.
- **`test_multiple_users_access` и `test_admin_access_restrictions` пропускали
  себя сами.** `pytest.skip("No devices available")` стоял **до** всякой
  проверки прав. То есть тест был зелёным, ни разу не проверив доступ, — это
  опаснее падения: падение хотя бы видно, а здесь отчёт говорил «проверено».

Причина пропуска устранена устранением её настоящей причины: устройство
теперь гарантированно создаётся фикстурой через настоящую синхронизацию, и
отсутствие устройства сделано ошибкой, а не поводом пропустить тест.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.helpers.ha_stub import HAUnavailable, stub_ha


@pytest.fixture
def source_id(isolated_client):
    """Созданный источник внешней системы.

    Args:
        isolated_client: HTTP-клиент теста.

    Returns:
        Идентификатор источника.
    """
    response = isolated_client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Access Control HA",
            "url": "http://access.invalid:8123",
            "token": "access_token_12345",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pytest.fixture
def synced_device_id(isolated_client, source_id, ha_states):
    """Устройство, полученное синхронизацией источника.

    Создаётся всегда, а не «если повезёт»: прежние тесты брали первое
    устройство из списка и пропускали себя, если список оказывался пустым.
    Пустой список означал бы, что проверка прав так и не состоялась.

    Args:
        isolated_client: HTTP-клиент теста.
        source_id: Идентификатор источника.
        ha_states: Состояния внешней системы.

    Returns:
        Идентификатор устройства.
    """
    with stub_ha(states=ha_states):
        sync = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
    assert sync.status_code == 200, sync.text

    devices = isolated_client.get("/api/v1/devices").json()
    assert devices, (
        "синхронизация обязана была создать устройство; пустой список означал бы, "
        "что проверка прав не состоялась"
    )
    return str(devices[0]["id"])


def _as(client: TestClient, user_id: str, is_admin: bool = False) -> TestClient:
    """Создаёт клиента, действующего строго от имени указанного пользователя.

    Отдельный клиент, а не заголовки у запроса, — обязателен. httpx **сливает**
    заголовки запроса с дефолтными заголовками клиента, а не заменяет их. Если
    у клиента стоит `X-Is-Admin: true`, то переопределение только `X-User-ID`
    оставит признак администратора, и пользователь получит admin-bypass:
    `devices.py:65` начинает проверку с `if is_admin: return`. Роль `viewer`
    получала бы 200 вместо 403, а проверка прав проходила бы, ничего не
    проверяя, — ровно та ошибка, которую фича и устраняет.

    Args:
        client: Клиент-образец, у которого читается приложение.
        user_id: Идентификатор пользователя.
        is_admin: Действовать ли от имени администратора.

    Returns:
        Клиент с ровно теми заголовками, что заданы здесь.
    """
    headers = {"X-User-ID": user_id}
    if is_admin:
        headers["X-Is-Admin"] = "true"
    else:
        headers["X-Is-Admin"] = "false"
    return TestClient(client.app, headers=headers)


def _grant(client: TestClient, device_id: str, user_id: str, role: str) -> dict:
    """Назначает доступ пользователю от имени администратора.

    Args:
        client: Клиент администратора.
        device_id: Идентификатор устройства.
        user_id: Идентификатор пользователя.
        role: Назначаемая роль.

    Returns:
        Тело ответа с записью о доступе.
    """
    response = client.post(
        f"/api/v1/devices/{device_id}/access",
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201, f"ожидался 201: {response.text}"
    return dict(response.json())


class TestFullAccessControlFlow:
    """Сквозной сценарий: назначение → видимость → команды → отзыв."""

    def test_complete_access_lifecycle(self, isolated_client, synced_device_id):
        """Полный поток управления доступом к устройству.

        Шаги проверяют и положительный, и отрицательный исход на каждом этапе:
        пользователь без доступа не видит устройство, с ролью `viewer` видит,
        но не управляет, с ролью `controller` управляет, а после отзыва снова
        не видит и не управляет.
        """
        device_id = synced_device_id
        stranger = _as(isolated_client, "user_without_rights")
        viewer = _as(isolated_client, "user_viewer")

        # 1. Пользователь без доступа не видит устройство
        stranger_devices = stranger.get("/api/v1/devices")
        assert stranger_devices.status_code == 200
        assert device_id not in [d["id"] for d in stranger_devices.json()], (
            "пользователь без доступа не должен видеть устройство"
        )

        # 2. Администратор назначает роль только для чтения
        access = _grant(isolated_client, device_id, "user_viewer", "viewer")
        assert access["role"] == "viewer", f"роль не применена: {access}"
        assert access["user_id"] == "user_viewer", f"доступ выдан не тому: {access}"

        # 3. Теперь устройство видно
        viewer_devices = viewer.get("/api/v1/devices")
        assert device_id in [d["id"] for d in viewer_devices.json()], (
            "пользователь с доступом должен видеть устройство"
        )

        detail = viewer.get(f"/api/v1/devices/{device_id}")
        assert detail.status_code == 200, f"ожидался доступ к карточке: {detail.text}"

        # 4. Роль viewer не позволяет управлять
        denied = viewer.post(
            f"/api/v1/devices/{device_id}/command", json={"command_name": "turn_off"}
        )
        assert denied.status_code == 403, (
            f"роль viewer обязана давать отказ, получен {denied.status_code}: {denied.text}"
        )

        # 5. Повышение до controller
        elevated = _grant(isolated_client, device_id, "user_viewer", "controller")
        assert elevated["role"] == "controller", f"роль не повышена: {elevated}"

        # Повышение роли **пересоздаёт** запись: `grant_access` удаляет прежнюю
        # и создаёт новую с новым идентификатором (`device_service.py:990-1000`).
        # Отзыв по прежнему `access_id` дал бы 404 — то есть тест проверял бы
        # не отзыв доступа, а отсутствие записи.
        assert elevated["id"] != access["id"], "повышение роли обязано обновить запись"

        # 6. Теперь команда проходит
        allowed = viewer.post(
            f"/api/v1/devices/{device_id}/command", json={"command_name": "turn_off"}
        )
        assert allowed.status_code == 200, (
            f"роль controller обязана позволять команду, получен {allowed.status_code}"
        )

        # 7. Администратор отзывает доступ
        revoked = isolated_client.delete(f"/api/v1/devices/{device_id}/access/{elevated['id']}")
        assert revoked.status_code == 204, f"ожидался 204: {revoked.text}"

        # 8. После отзыва устройство снова не видно и недоступно
        after_devices = viewer.get("/api/v1/devices")
        assert device_id not in [d["id"] for d in after_devices.json()], (
            "после отзыва устройство не должно быть видно"
        )

        after_detail = viewer.get(f"/api/v1/devices/{device_id}")
        assert after_detail.status_code == 403, (
            f"после отзыва карточка обязана быть недоступна: {after_detail.text}"
        )

        after_command = viewer.post(
            f"/api/v1/devices/{device_id}/command", json={"command_name": "turn_on"}
        )
        assert after_command.status_code == 403, (
            f"после отзыва команда обязана отклоняться: {after_command.text}"
        )


class TestMultipleUsersAccess:
    """Разные роли для разных пользователей."""

    def test_different_users_have_different_rights(self, isolated_client, synced_device_id):
        """Два пользователя с разными ролями получают разные возможности.

        Суть проверки — что права действительно разграничиваются, а не что все
        проходят. Раньше тест пропускал себя при пустом списке устройств, то
        есть проверял бы, скорее всего, ничего.
        """
        device_id = synced_device_id

        _grant(isolated_client, device_id, "user_viewer", "viewer")
        _grant(isolated_client, device_id, "user_other", "controller")

        viewer_command = _as(isolated_client, "user_viewer").post(
            f"/api/v1/devices/{device_id}/command", json={"command_name": "turn_on"}
        )
        other_command = _as(isolated_client, "user_other").post(
            f"/api/v1/devices/{device_id}/command", json={"command_name": "turn_on"}
        )

        assert viewer_command.status_code == 403, (
            f"роль viewer обязана давать отказ: {viewer_command.text}"
        )
        assert other_command.status_code == 200, (
            f"роль controller обязана позволять команду: {other_command.text}"
        )

    def test_both_users_see_the_device(self, isolated_client, synced_device_id):
        """Оба пользователя видят устройство независимо от роли."""
        device_id = synced_device_id
        _grant(isolated_client, device_id, "user_viewer", "viewer")
        _grant(isolated_client, device_id, "user_other", "controller")

        for user in ("user_viewer", "user_other"):
            devices = _as(isolated_client, user).get("/api/v1/devices").json()
            assert device_id in [d["id"] for d in devices], (
                f"пользователь {user} должен видеть устройство: {devices}"
            )

    def test_revoke_one_user_leaves_others_intact(self, isolated_client, synced_device_id):
        """Отзыв доступа одному не затрагивает остальных."""
        device_id = synced_device_id
        revoked_access = _grant(isolated_client, device_id, "user_viewer", "viewer")
        _grant(isolated_client, device_id, "user_other", "controller")

        revoke = isolated_client.delete(
            f"/api/v1/devices/{device_id}/access/{revoked_access['id']}"
        )
        assert revoke.status_code == 204, revoke.text

        gone = _as(isolated_client, "user_viewer").get("/api/v1/devices").json()
        assert device_id not in [d["id"] for d in gone], "доступ отозван, устройство не видно"

        remaining = _as(isolated_client, "user_other").get("/api/v1/devices").json()
        assert device_id in [d["id"] for d in remaining], "доступ другого не должен страдать"


class TestAdminRestrictions:
    """Только администратор управляет доступом."""

    def test_only_admin_can_grant_access(self, isolated_client, synced_device_id):
        """Обычный пользователь не может назначить доступ."""
        device_id = synced_device_id

        denied = _as(isolated_client, "user_without_rights").post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )
        assert denied.status_code == 403, f"ожидался 403 для не-администратора: {denied.text}"

        allowed = isolated_client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )
        assert allowed.status_code == 201, f"администратор должен получать 201: {allowed.text}"

    def test_non_admin_cannot_revoke_access(self, isolated_client, synced_device_id):
        """Обычный пользователь не может отозвать доступ."""
        device_id = synced_device_id
        granted = _grant(isolated_client, device_id, "user_viewer", "viewer")

        viewer = _as(isolated_client, "user_viewer")

        denied = viewer.delete(f"/api/v1/devices/{device_id}/access/{granted['id']}")
        assert denied.status_code == 403, f"ожидался 403: {denied.text}"

        # Доступ должен остаться: отказ не должен иметь эффекта
        still_visible = viewer.get("/api/v1/devices").json()
        assert device_id in [d["id"] for d in still_visible], (
            "отклонённый отзыв не должен менять доступ"
        )

    def test_non_admin_cannot_list_access_records(self, isolated_client, synced_device_id):
        """Обычный пользователь не видит список записей о доступе."""
        device_id = synced_device_id
        _grant(isolated_client, device_id, "user_viewer", "viewer")

        denied = _as(isolated_client, "user_viewer").get(f"/api/v1/devices/{device_id}/access")
        assert denied.status_code == 403, f"ожидался 403: {denied.text}"


class TestAccessValidation:
    """Валидация назначения доступа."""

    def test_grant_before_sync_is_allowed(self, isolated_client):
        """Доступ выдаётся до синхронизации — назначение «слепое» к устройству.

        Первая версия теста требовала 404 для несуществующего устройства. Это
        противоречит сознательному решению specs/004: доступ выдаётся на
        идентификатор до того, как устройство появится, иначе права нельзя
        было бы подготовить заранее — до первой синхронизации источника.
        Реализация это подтверждает (`device_service.py:976-977`).

        Тест фиксирует наблюдаемое поведение, чтобы изменение решения было
        осознанным, а не случайным.
        """
        device_id = uuid4()

        response = isolated_client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )

        assert response.status_code == 201, f"ожидался 201: {response.text}"
        assert response.json()["device_id"] == str(device_id)

    def test_invalid_role_is_rejected(self, isolated_client, synced_device_id):
        """Неизвестная роль отклоняется."""
        response = isolated_client.post(
            f"/api/v1/devices/{synced_device_id}/access",
            json={"user_id": "user_viewer", "role": "superuser"},
        )

        assert response.status_code == 400, f"ожидался 400 для неверной роли: {response.text}"

    def test_empty_user_id_is_rejected(self, isolated_client, synced_device_id):
        """Пустой идентификатор пользователя отклоняется."""
        response = isolated_client.post(
            f"/api/v1/devices/{synced_device_id}/access",
            json={"user_id": "", "role": "viewer"},
        )

        assert response.status_code == 422, f"ожидался 422: {response.text}"

    def test_access_requires_identity(self, isolated_app, synced_device_id):
        """Назначение доступа без идентичности отклоняется с 401."""
        with TestClient(isolated_app) as anonymous:
            response = anonymous.post(
                f"/api/v1/devices/{synced_device_id}/access",
                json={"user_id": "user_viewer", "role": "viewer"},
            )

        assert response.status_code == 401, f"ожидался 401: {response.text}"

    def test_revoke_unknown_access_record_returns_404(self, isolated_client, synced_device_id):
        """Отзыв несуществующей записи — 404."""
        response = isolated_client.delete(f"/api/v1/devices/{synced_device_id}/access/{uuid4()}")

        assert response.status_code == 404, f"ожидался 404: {response.text}"


class TestAccessUnderSystemFailure:
    """Права при недоступной внешней системе."""

    def test_device_remains_visible_after_failed_sync(
        self, isolated_client, source_id, ha_states, synced_device_id
    ):
        """Сбой синхронизации не отбирает доступ к устройству.

        Сценарий проверяет связку прав и отказов: устройство остаётся
        доступным администратору даже когда система недоступна.

        Args:
            isolated_client: HTTP-клиент теста.
            source_id: Идентификатор источника.
            ha_states: Состояния внешней системы.
            synced_device_id: Идентификатор устройства.
        """
        _grant(isolated_client, synced_device_id, "user_viewer", "viewer")

        with stub_ha(mode=HAUnavailable.REFUSED):
            failed = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert failed.status_code == 500, f"ожидался отказ синхронизации: {failed.text}"

        devices = isolated_client.get(
            "/api/v1/devices", headers={"X-User-ID": "user_viewer"}
        ).json()
        assert synced_device_id in [d["id"] for d in devices], (
            f"сбой синхронизации не должен отбирать доступ: {devices}"
        )


class TestDeviceEventDeliveryRights:
    """Спека 004 US3: доставка событий по правам (проверка при каждой доставке)."""

    def test_device_event_delivery_revoked_after_revoke(
        self, admin_user_id, regular_user_id, isolated_app
    ):
        """T014: подписка с доступом → событие доставлено; после отзыва → не доставлено.

        Args:
            admin_user_id: Идентификатор администратора.
            regular_user_id: Идентификатор подписчика.
            isolated_app: Приложение на изолированном хранилище.

        Замечание: раньше тест брал синглтон `src.main.app`, который создаётся
        при импорте модуля и замыкает путь `data/` репозитория до входа в
        фикстуры. Из-за этого каждое выполнение оставляло в настоящем журнале
        событий две записи (+768 байт) — утечку, невидимую при сканировании по
        размеру, потому что `device_access.json` после revoke возвращался к
        исходному состоянию. Теперь используется изолированное приложение.
        """
        device_id = str(uuid4())
        headers = {"X-User-ID": admin_user_id, "X-Is-Admin": "true"}

        with TestClient(isolated_app, headers=headers) as client:
            # Выдаём viewer-доступ обычному пользователю (grant до синка — device-blind)
            grant = client.post(
                f"/api/v1/devices/{device_id}/access",
                json={"user_id": regular_user_id, "role": "viewer"},
                headers=headers,
            )
            assert grant.status_code in [200, 201]

            # ВАЖНО: импорт из того же модуля, который использует приложение.
            # Разные имена (`webui.*` и `src.webui.*`) дают разные экземпляры
            # модуля и, следовательно, разные connection_manager.
            from webui.routes.devices.websocket import broadcast_state_change

            with client.websocket_connect("/api/v1/ws/devices") as ws:
                ws.send_json({"type": "auth", "user_id": regular_user_id})
                auth_reply = ws.receive_json()
                assert auth_reply["type"] == "authenticated"

                ws.send_json({"type": "subscribe", "device_id": device_id})
                sub_reply = ws.receive_json()
                assert sub_reply["type"] == "subscribed"

                # Событие доставлено (доступ есть) — broadcast в портале TestClient
                client.portal.call(broadcast_state_change, device_id, {"state": "on"})
                delivered = ws.receive_json()
                assert delivered["type"] == "state_changed"
                assert delivered["device_id"] == device_id

            # Отзываем доступ
            access_id = grant.json()["id"]
            revoke = client.delete(
                f"/api/v1/devices/{device_id}/access/{access_id}", headers=headers
            )
            assert revoke.status_code in [200, 204]

            # Новое соединение (прошлая закрыта context manager'ом)
            with client.websocket_connect("/api/v1/ws/devices") as ws:
                ws.send_json({"type": "auth", "user_id": regular_user_id})
                ws.receive_json()

                ws.send_json({"type": "subscribe", "device_id": device_id})
                sub_reply = ws.receive_json()
                # Доступ отозван — подписка отклоняется
                assert sub_reply["type"] == "error", f"ожидался error: {sub_reply}"


class TestAccessPersistenceAcrossRestarts:
    """Спека 004 US2: доступы переживают перезапуск (FR-010, SC-004)."""

    def test_access_survives_service_restart(
        self, admin_user_id, regular_user_id, isolated_workdir
    ):
        """T019: grant → пересоздать DeviceService → доступ сохранился.

        Args:
            admin_user_id: Идентификатор администратора.
            regular_user_id: Идентификатор получателя доступа.
            isolated_workdir: Временный рабочий каталог. Используется ради
                изоляции: `PersistenceManager(data_dir="data")` разрешает путь
                от текущего каталога, поэтому без него тест писал бы в
                каталог данных репозитория.
        """
        import asyncio
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.persistence.manager import PersistenceManager
        from services.device_service import DeviceService

        device_id = uuid4()

        async def flow():
            svc = DeviceService(
                event_bus=EventBus(),
                persistence_module=PersistenceManager(data_dir="data"),
                ha_adapter=None,
            )
            grant = await svc.grant_access(
                device_id=device_id,
                user_id=regular_user_id,
                role="controller",
                granted_by=admin_user_id,
            )
            assert grant is not None, "grant должен создаться"

            # «Перезапуск»: новый экземпляр сервиса с той же персистентностью
            restarted = DeviceService(
                event_bus=EventBus(),
                persistence_module=PersistenceManager(data_dir="data"),
                ha_adapter=None,
            )
            accesses = await restarted.get_device_accesses(device_id)
            return [a for a in accesses if a.user_id == regular_user_id], restarted, device_id

        records, restarted_svc, dev_id = asyncio.run(flow())

        assert len(records) == 1, f"ожидалась 1 запись после перезапуска: {records}"
        assert records[0].role == "controller"

        # Проверка доступа через перезапущенный сервис
        ok = asyncio.run(
            restarted_svc.check_device_access(UUID(str(dev_id)), regular_user_id, "viewer")
        )
        assert ok is True

        # Убираем за собой
        asyncio.run(restarted_svc.revoke_access(records[0].id))
