"""Список устройств и глобальный администратор (Known Issue #41).

Проверяет одно: `GET /api/v1/devices` делит правило видимости с остальными
device-endpoints. Администратор помечен `X-Is-Admin: true` и должен получать
полный список независимо от записей доступа; не-администратор — только свои
устройства. Обе половины проверяются на **настоящих** устройствах в
единственном источнике (`DeviceService`).

Почему отдельный файл, а не `test_device_access_rights.py`
--------------------------------------------------------
Там устройства появляются **синхронизацией источника**, а синхронизация сама
выдаёт права: `DeviceService._grant_sync_access` (`src/services/device_service.py:217-234`)
создаёт запись доступа для жёстко зашитого `SYNC_ACCESS_USER = "admin_user"`
(`:46`). Администратор в этих тестах — тоже `admin_user` (фикстура
`admin_user_id`), поэтому он видит устройства по записи доступа, а не по
признаку `X-Is-Admin`.

Следствие: админская проверка в том файле зелёная и на сломанной реализации —
она не отличает обход признака администратора от фильтрации по записям
(ровно тот дефект, который здесь и чинится). Отличить одно от другого можно
только устройством **без единой записи доступа** и администратором с другим
именем. Такая подготовка в общий файл с синхронизацией не годится: два
разных предусловия в одном наборе читались бы как одно.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Ловушка httpx
-------------
Заголовки запроса **сливаются** с дефолтными заголовками клиента, а не
заменяют их. Если у клиента стоит `X-Is-Admin: true`, то переопределение
только `X-User-ID` оставит признак администратора — и не-администратор
получит admin-bypass. Поэтому каждый тест берёт отдельного клиента с ровно
теми заголовками, которые ему нужны (`_as`).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


#: Администратор проверок. Намеренно **не** `admin_user`: у этого имени
#: синхронизация источника создаёт записи доступа, и проверка обхода была бы
#: неотличима от фильтрации по записям.
ADMIN_USER_ID = "chief_admin"

#: Обычный пользователь с выданным доступом.
VIEWER_USER_ID = "user_viewer"

#: Обычный пользователь без единого доступа.
OUTSIDER_USER_ID = "user_without_rights"


def _as(client: TestClient, user_id: str, is_admin: bool = False) -> TestClient:
    """Создаёт клиента, действующего строго от имени указанного пользователя.

    Отдельный клиент обязателен: httpx **сливает** заголовки запроса с
    дефолтными заголовками клиента, а не заменяет их (см. модульный
    докстринг и `test_device_access_rights.py::_as`).

    Args:
        client: Клиент-образец, у которого читается приложение.
        user_id: Идентификатор пользователя.
        is_admin: Действовать ли от имени администратора.

    Returns:
        Клиент с ровно теми заголовками, что заданы здесь.
    """
    headers = {"X-User-ID": user_id, "X-Is-Admin": "true" if is_admin else "false"}
    return TestClient(client.app, headers=headers)


def _grant(isolated_client: TestClient, device_id: str, user_id: str) -> None:
    """Выдаёт доступ к устройству через API и проверяет, что запись создалась.

    Args:
        isolated_client: Клиент администратора.
        device_id: Идентификатор устройства.
        user_id: Кому выдаётся доступ.
    """
    granted = isolated_client.post(
        f"/api/v1/devices/{device_id}/access",
        json={"user_id": user_id, "role": "viewer"},
    )
    assert granted.status_code == 201, granted.text


def _listed(response: Any) -> set[str]:
    """Извлекает множество идентификаторов устройств из ответа списка.

    Args:
        response: Ответ `GET /api/v1/devices`.

    Returns:
        Множество строковых идентификаторов устройств.
    """
    assert response.status_code == 200, response.text
    return {str(device["id"]) for device in response.json()}


@pytest.fixture
def devices_without_access(isolated_app: Any, isolated_client: TestClient) -> dict[str, str]:
    """Два устройства в двух источниках, у которых нет ни одной записи о доступе.

    Посев идёт прямо в `DeviceService` — единственный источник роутов
    (spec 006, FR-003), — а не через синхронизацию источника: синхронизация
    выдаёт права `admin_user` сама, и предусловие проверки было бы нарушено
    самой подготовкой. Разные источники нужны, чтобы отличить фильтр
    `source_id` от «показал всё».

    Предусловие **проверяется**, а не предполагается: у обоих устройств не
    должно быть ни одной записи доступа, иначе проверка обхода прошла бы и
    на неисправном коде.

    Args:
        isolated_app: Приложение на изолированном хранилище.
        isolated_client: Клиент администратора (для проверки предусловия).

    Returns:
        Идентификаторы устройств и их источников.
    """
    from tests.helpers.device_factory import make_device, seed_device_in_service

    service = isolated_app.state.device_service
    first_source, second_source = uuid4(), uuid4()
    first = seed_device_in_service(
        service,
        make_device(
            ha_entity_id="light.admin_probe",
            source_id=first_source,
            name="Первый зонд",
        ),
    )
    second = seed_device_in_service(
        service,
        make_device(
            ha_entity_id="switch.admin_probe",
            source_id=second_source,
            name="Второй зонд",
        ),
    )

    device_ids = (str(first.id), str(second.id))
    for device_id in device_ids:
        # Устройство обязано существовать и читаться одиночным запросом:
        # иначе пустой список можно было бы объяснить отсутствием устройства.
        probe = isolated_client.get(f"/api/v1/devices/{device_id}")
        assert probe.status_code == 200, (
            f"подготовка не удалась: устройство {device_id} не читается через "
            f"GET /api/v1/devices/{device_id} (статус={probe.status_code}, "
            f"тело={probe.text})"
        )
        records = isolated_client.get(f"/api/v1/devices/{device_id}/access")
        assert records.status_code == 200, records.text
        assert records.json() == [], (
            f"подготовка не удалась: у устройства {device_id} уже есть записи "
            f"доступа, проверка обхода была бы неотличима от фильтрации "
            f"по записям: {records.json()}"
        )

    return {
        "first_id": str(first.id),
        "second_id": str(second.id),
        "first_source_id": str(first_source),
        "second_source_id": str(second_source),
    }


class TestAdminListBypass:
    """Глобальный администратор видит список независимо от записей доступа."""

    def test_admin_without_access_records_sees_device(
        self, isolated_client: TestClient, devices_without_access: dict[str, str]
    ) -> None:
        """Администратор без единой записи видит устройство — главный симптом.

        Пустой ответ здесь означает именно потерю видимости у администратора:
        устройство посеяно в единственный источник и читается одиночным
        `GET /devices/{id}` (это проверяет фикстура), поэтому «устройства нет»
        как объяснение пустого списка отпадает.

        Args:
            isolated_client: Клиент по умолчанию (нужен для создания клиента).
            devices_without_access: Устройства и источники без записей доступа.
        """
        admin = _as(isolated_client, ADMIN_USER_ID, is_admin=True)

        listed = _listed(admin.get("/api/v1/devices"))

        assert devices_without_access["first_id"] in listed, (
            f"администратор {ADMIN_USER_ID} без записей доступа должен видеть "
            f"устройство {devices_without_access['first_id']}, в списке: {listed}"
        )

    def test_admin_sees_devices_with_and_without_access_records(
        self, isolated_client: TestClient, devices_without_access: dict[str, str]
    ) -> None:
        """Администратор получает все устройства: и с записью, и без неё.

        Доступ выдан **другому** пользователю: записи доступа самого
        администратора по-прежнему нет ни на одном устройстве, поэтому видно
        только то, что обход признака администратора работает на обоих
        устройствах.

        Args:
            isolated_client: Клиент администратора.
            devices_without_access: Устройства и источники без записей доступа.
        """
        _grant(isolated_client, devices_without_access["second_id"], VIEWER_USER_ID)
        admin = _as(isolated_client, ADMIN_USER_ID, is_admin=True)

        listed = _listed(admin.get("/api/v1/devices"))
        expected = {
            devices_without_access["first_id"],
            devices_without_access["second_id"],
        }

        assert listed == expected, (
            f"администратор должен видеть все устройства установки, "
            f"ожидалось {expected}, получено {listed}"
        )

    def test_admin_source_filter_narrows_list(
        self, isolated_client: TestClient, devices_without_access: dict[str, str]
    ) -> None:
        """Фильтр `source_id` применяется к администратору, а не игнорируется.

        Фильтр накладывается **поверх** выбранного набора. Если бы он был
        потерян, администратор получил бы оба устройства — ровно тот
        наблюдаемый результат, что и без фильтрации доступа.

        Args:
            isolated_client: Клиент по умолчанию (нужен для создания клиента).
            devices_without_access: Устройства и источники без записей доступа.
        """
        admin = _as(isolated_client, ADMIN_USER_ID, is_admin=True)

        listed = _listed(
            admin.get(f"/api/v1/devices?source_id={devices_without_access['second_source_id']}")
        )

        assert listed == {devices_without_access["second_id"]}, (
            f"фильтр source_id должен оставить устройство своего источника, "
            f"ожидалось {{{devices_without_access['second_id']}}}, получено {listed}"
        )


class TestNonAdminListFiltering:
    """Для остальных видимость остаётся по записям доступа.

    Класс — страховка от обратной ошибки: обход администратора не должен был
    получен ослаблением фильтрации. Если эти тесты падают вместе с правкой,
    «починка» расширила права, а не восстановила их.
    """

    def test_non_admin_without_access_gets_empty_list(
        self, isolated_client: TestClient, devices_without_access: dict[str, str]
    ) -> None:
        """Без доступа не-администратор по-прежнему получает пустой список.

        Устройства заведомо существуют (проверяет фикстура), поэтому пустой
        список означает ограничение доступа, а не «устройств нет».

        Args:
            isolated_client: Клиент по умолчанию (нужен для создания клиента).
            devices_without_access: Устройства и источники без записей доступа.
        """
        outsider = _as(isolated_client, OUTSIDER_USER_ID)

        assert _listed(outsider.get("/api/v1/devices")) == set(), (
            "пользователь без единой записи доступа должен получать пустой список"
        )

    def test_non_admin_sees_only_granted_device(
        self, isolated_client: TestClient, devices_without_access: dict[str, str]
    ) -> None:
        """С выданным доступом не-администратор видит ровно свои устройства.

        Ключевая проверка класса: она отличает «отфильтровал по записям» от
        «показал всё» и от «показал ничего».

        Args:
            isolated_client: Клиент администратора.
            devices_without_access: Устройства и источники без записей доступа.
        """
        _grant(isolated_client, devices_without_access["first_id"], VIEWER_USER_ID)
        insider = _as(isolated_client, VIEWER_USER_ID)

        listed = _listed(insider.get("/api/v1/devices"))

        assert listed == {devices_without_access["first_id"]}, (
            f"ожидалось ровно устройство с доступом "
            f"{{{devices_without_access['first_id']}}}, получено {listed}"
        )
