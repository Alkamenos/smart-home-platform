"""Разграничение прав на существующем устройстве (спека 009, T025).

Проверяет, что фильтрация списка и разграничение доступа действительно
работают — на устройстве, которое **заведомо существует**. Это и есть
существенная часть проверки: на несуществующем устройстве почти любой ответ
выглядит как «доступ ограничен», и проверка прав становится неотличимой от
проверки несуществования.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Зачем эти тесты
---------------
Фильтрация списка реализована (`devices.py:143-144`) и, судя по отчётам о
покрытии, считалась покрытой. На деле она **не проверялась ни одним обращением
по HTTP**: ни один тест не убеждался, что устройство, к которому у
пользователя нет доступа, действительно отсутствует в выдаче, а устройство, к
которому доступ есть, — присутствует.

Ни один ассерт здесь не допускает «пустой список или отказ по
несуществованию». Такой допуск делает проверку неразличимой между «работает»
и «устройства нет», то есть обесценивает её целиком.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _as(client: TestClient, user_id: str, is_admin: bool = False) -> TestClient:
    """Создаёт клиента, действующего строго от имени указанного пользователя.

    Отдельный клиент, а не заголовки у запроса, обязателен: httpx **сливает**
    заголовки запроса с дефолтными заголовками клиента, а не заменяет их.
    Если у клиента стоит `X-Is-Admin: true`, то переопределение только
    `X-User-ID` оставит признак администратора — и пользователь без прав
    получит admin-bypass. Тогда все проверки «ожидаем отказ» прошли бы
    вхолостую, а проверки «ожидаем успех» обманули бы читателя вывода.

    Args:
        client: Клиент-образец, у которого читается приложение.
        user_id: Идентификатор пользователя.
        is_admin: Действовать ли от имени администратора.

    Returns:
        Клиент с ровно теми заголовками, что заданы здесь.
    """
    headers = {"X-User-ID": user_id, "X-Is-Admin": "true" if is_admin else "false"}
    return TestClient(client.app, headers=headers)


@pytest.fixture
def device_ids(isolated_client, synced_device_id) -> dict:
    """Две пары «устройство — пользователь с доступом».

    Нужны две, а не одно: проверка «список отдаёт только доступное» обязана
    отличать одно устройство от другого, иначе откат фильтрации дал бы пустой
    список — то есть результат, неотличимый от корректной работы.

    Args:
        isolated_client: HTTP-клиент теста.
        synced_device_id: Идентификатор устройства.

    Returns:
        Словарь «устройство → идентификатор пользователя без доступа».
    """
    second = isolated_client.get("/api/v1/devices").json()[1]["id"]

    return {
        "first": str(synced_device_id),
        "second": str(second),
        "outsider": "user_without_rights",
        "insider": "user_viewer",
    }


class TestListFilteringByAccess:
    """Список устройств отдаёт только доступное пользователю."""

    def test_list_excludes_device_without_access(self, isolated_client, device_ids):
        """Устройство без записи о доступе не попадает в список."""
        granted = isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )
        assert granted.status_code == 201, granted.text

        outsider = _as(isolated_client, device_ids["outsider"])
        devices = outsider.get("/api/v1/devices")

        assert devices.status_code == 200, devices.text
        listed = {str(d["id"]) for d in devices.json()}
        assert device_ids["first"] not in listed, (
            f"устройство без доступа не должно попадать в список: {listed}"
        )

    def test_list_includes_granted_device(self, isolated_client, device_ids):
        """Устройство с доступом попадает в список.

        Парная проверка к предыдущей: без неё «исключено» проверялось бы и
        на пустом списке, то есть прошло бы и при полной неработе фильтрации.
        """
        granted = isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )
        assert granted.status_code == 201, granted.text

        insider = _as(isolated_client, device_ids["insider"])
        devices = insider.get("/api/v1/devices")

        assert devices.status_code == 200, devices.text
        listed = {str(d["id"]) for d in devices.json()}
        assert device_ids["first"] in listed, (
            f"устройство с доступом должно попадать в список: {listed}"
        )

    def test_list_contains_only_own_device(self, isolated_client, device_ids):
        """В списке ровно то устройство, к которому выдан доступ.

        Ключевая проверка: она отличает «отфильтровал» от «показал всё» и от
        «показал ничего».
        """
        isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )

        insider = _as(isolated_client, device_ids["insider"])
        listed = {str(d["id"]) for d in insider.get("/api/v1/devices").json()}

        assert listed == {device_ids["first"]}, (
            f"ожидалось ровно одно устройство с доступом, получено {listed}"
        )

    def test_second_grant_widens_list(self, isolated_client, device_ids):
        """Второй доступ расширяет список ровно на одно устройство."""
        for key in ("first", "second"):
            granted = isolated_client.post(
                f"/api/v1/devices/{device_ids[key]}/access",
                json={"user_id": "user_viewer", "role": "viewer"},
            )
            assert granted.status_code == 201, granted.text

        insider = _as(isolated_client, device_ids["insider"])
        listed = {str(d["id"]) for d in insider.get("/api/v1/devices").json()}

        assert listed == {device_ids["first"], device_ids["second"]}, (
            f"ожидались оба устройства, получено {listed}"
        )

    def test_admin_sees_all_devices(self, isolated_client, device_ids):
        """Администратор видит всё — фильтрация не должна ломать его обзор."""
        admin = _as(isolated_client, "admin_user", is_admin=True)
        listed = {str(d["id"]) for d in admin.get("/api/v1/devices").json()}

        assert device_ids["first"] in listed
        assert device_ids["second"] in listed

    def test_revocation_narrows_list_back(self, isolated_client, device_ids):
        """Отзыв доступа убирает устройство из списка."""
        granted = isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )
        assert granted.status_code == 201, granted.text

        revoke = isolated_client.delete(
            f"/api/v1/devices/{device_ids['first']}/access/{granted.json()['id']}"
        )
        assert revoke.status_code == 204, revoke.text

        insider = _as(isolated_client, device_ids["insider"])
        listed = {str(d["id"]) for d in insider.get("/api/v1/devices").json()}

        assert device_ids["first"] not in listed, (
            f"после отзыва устройства быть не должно: {listed}"
        )


class TestDirectAccessToDevice:
    """Прямое обращение к устройству подчиняется тем же правилам."""

    def test_detail_is_available_with_access(self, isolated_client, device_ids):
        """С доступом карточка устройства читается."""
        isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )

        insider = _as(isolated_client, device_ids["insider"])
        detail = insider.get(f"/api/v1/devices/{device_ids['first']}")

        assert detail.status_code == 200, f"ожидался 200: {detail.text}"
        assert str(detail.json()["id"]) == device_ids["first"]

    def test_detail_is_denied_without_access(self, isolated_client, device_ids):
        """Без доступа карточка недоступна.

        Ответ обязан быть именно `403`: устройство существует, поэтому `404`
        означала бы попытку скрыть сам факт существования, а не ограничить
        доступ. Допускать оба кода здесь нельзя — это разные решения.
        """
        outsider = _as(isolated_client, device_ids["outsider"])
        detail = outsider.get(f"/api/v1/devices/{device_ids['first']}")

        assert detail.status_code == 403, (
            f"ожидался 403 для существующего устройства без доступа, "
            f"получено {detail.status_code}: {detail.text}"
        )

    def test_denied_detail_does_not_leak_device_data(self, isolated_client, device_ids):
        """Отказ не раскрывает данных устройства."""
        outsider = _as(isolated_client, device_ids["outsider"])
        detail = outsider.get(f"/api/v1/devices/{device_ids['first']}")

        assert detail.status_code == 403
        leaked = set(detail.json()) & {"ha_entity_id", "state", "name", "config"}
        assert not leaked, f"ответ на отказ раскрывает поля устройства: {detail.json()}"

    def test_access_is_revoked_immediately(self, isolated_client, device_ids):
        """После отзыва прямое обращение перестаёт работать.

        Проверяется на том же устройстве, что и выдача доступа, — иначе отзыв
        был бы неотличим от «устройства нет».
        """
        granted = isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "viewer"},
        )
        insider = _as(isolated_client, device_ids["insider"])
        before = insider.get(f"/api/v1/devices/{device_ids['first']}")
        assert before.status_code == 200, before.text

        revoke = isolated_client.delete(
            f"/api/v1/devices/{device_ids['first']}/access/{granted.json()['id']}"
        )
        assert revoke.status_code == 204, revoke.text

        after = insider.get(f"/api/v1/devices/{device_ids['first']}")
        assert after.status_code == 403, (
            f"после отзыва ожидался 403, получено {after.status_code}: {after.text}"
        )

    def test_denied_command_is_not_executed(self, isolated_client, device_ids):
        """Отказ в команде не сопровождается её выполнением.

        Ошибка означала бы, что команда ушла на устройство несмотря на отказ в
        доступе, — то есть ограничение декоративно.
        """
        outsider = _as(isolated_client, device_ids["outsider"])
        response = outsider.post(
            f"/api/v1/devices/{device_ids['first']}/command",
            json={"command_name": "turn_off"},
        )

        assert response.status_code == 403, f"ожидался 403: {response.text}"

        events = isolated_client.get(
            f"/api/v1/devices/{device_ids['first']}/events?event_type=command_executed"
        )
        records = events.json()
        assert not records, f"отклонённая команда не должна попасть в историю: {records}"


class TestCommandsUnderAccess:
    """Роль по доступу определяет возможность управления."""

    @pytest.mark.parametrize(
        ("role", "expected_status"),
        [("viewer", 403), ("controller", 202)],
    )
    def test_role_decides_command_outcome(
        self, isolated_client, device_ids, role: str, expected_status: int
    ):
        """Роль `viewer` не управляет, `controller` управляет.

        Параметризовано, чтобы пара «роль — исход» проверялась совместно: по
        отдельности каждая половина прошла бы и при сломанном назначении ролей.

        Args:
            isolated_client: HTTP-клиент теста.
            device_ids: Устройство и пользователи.
            role: Назначаемая роль.
            expected_status: Ожидаемый код ответа на команду.
        """
        granted = isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": role},
        )
        assert granted.status_code == 201, granted.text

        insider = _as(isolated_client, device_ids["insider"])
        response = insider.post(
            f"/api/v1/devices/{device_ids['first']}/command",
            json={"command_name": "turn_off"},
        )

        assert response.status_code == expected_status, (
            f"роль {role}: ожидался {expected_status}, получено {response.status_code}"
        )

    def test_controller_command_is_recorded(self, isolated_client, device_ids):
        """Разрешённая команда попадает в историю устройства.

        Без этой проверки «202» означал бы только «ответили успехом», а не
        «команда действительно выполнена».
        """
        granted = isolated_client.post(
            f"/api/v1/devices/{device_ids['first']}/access",
            json={"user_id": "user_viewer", "role": "controller"},
        )
        assert granted.status_code == 201, granted.text

        insider = _as(isolated_client, device_ids["insider"])
        response = insider.post(
            f"/api/v1/devices/{device_ids['first']}/command",
            json={"command_name": "turn_off"},
        )
        assert response.status_code == 202, response.text

        events = isolated_client.get(
            f"/api/v1/devices/{device_ids['first']}/events?event_type=command_executed"
        )
        records = events.json()
        assert len(records) == 1, f"ожидалась одна запись о команде: {records}"
        assert records[0]["data"]["command"] == "turn_off", (
            f"в истории должно быть имя выполненной команды: {records}"
        )
