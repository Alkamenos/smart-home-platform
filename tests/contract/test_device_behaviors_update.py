"""Маршрут правки поведений: проверка до записи (пункт 4 веб-плана).

`PUT /api/v1/devices/{id}/behaviors` — единственный путь, которым форма будет
менять настройки. Проверка обязана выполняться **до** обращения к сервису
жизненного цикла: устройство с отвергнутыми параметрами не должно ни менять
состояние, ни попасть в журнал аудита как обновлённое.

Пять слоёв проверки разбирать здесь не нужно — они закрыты в
`test_behavior_params_validation.py`. Здесь важно другое: маршрут действительно
вызывает проверку и действительно отказывает, а не пропускает всё подряд.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from fastapi.testclient import TestClient


def _make_device(client: TestClient) -> str:
    """Создаёт источник и устройство света, возвращает его идентификатор.

    Args:
        client: HTTP-клиент от имени администратора.

    Returns:
        Идентификатор устройства.
    """
    source = client.post(
        "/api/v1/devices/sources",
        json={
            "name": "Источник для правки поведений",
            "url": "http://192.168.1.13:8123",
            "token": "probe_token_long_enough",
        },
    )
    assert source.status_code == 201, source.text
    applied = client.post(
        "/api/v1/devices/apply",
        json={
            "source_id": source.json()["id"],
            "dry_run": False,
            "selections": [
                {
                    "device_entity_id": "light.behavior_probe",
                    "device_type": "light",
                    "name": "Свет для правки",
                    "target_room": "kitchen",
                    "behavior_template": "lighting",
                }
            ],
        },
    )
    assert applied.status_code == 201, applied.text
    return str(client.get("/api/v1/devices?ha_entity_id=light.behavior_probe").json()[0]["id"])


class TestDeviceFilterIsReal:
    """Фильтр `ha_entity_id` обязан сужать выборку (#74).

    Параметр был молчаливо игнорируем: запрос с фильтром возвращал все устройства.
    Проверки этого файла пользовались им и проходили не потому, что он работает,
    а потому что устройство в изолированном приложении было одно.
    """

    def test_should_return_only_requested_device(self, isolated_client: TestClient) -> None:
        """Фильтр оставляет ровно одно устройство.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        first = _make_device(isolated_client)

        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={"name": "Второй источник", "url": "http://192.168.1.14:8123", "token": "t" * 20},
        )
        assert source.status_code == 201, source.text
        isolated_client.post(
            "/api/v1/devices/apply",
            json={
                "source_id": source.json()["id"],
                "dry_run": False,
                "selections": [
                    {
                        "device_entity_id": "light.behavior_probe_two",
                        "device_type": "light",
                        "name": "Второй светильник",
                        "target_room": "kitchen",
                        "behavior_template": "lighting",
                    }
                ],
            },
        )

        listing = isolated_client.get("/api/v1/devices")

        assert len(listing.json()) == 2, "в изолированном приложении должно быть два устройства"
        filtered = isolated_client.get("/api/v1/devices?ha_entity_id=light.behavior_probe")

        assert [item["id"] for item in filtered.json()] == [first], (
            "фильтр не сузил выборку: вызывающий код получил бы все устройства, "
            "считая, что получил одно (Known Issue #74)"
        )

    def test_should_return_empty_list_for_unknown_entity(self, isolated_client: TestClient) -> None:
        """Неизвестный entity_id даёт пустой список, а не всё подряд.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        _make_device(isolated_client)

        response = isolated_client.get("/api/v1/devices?ha_entity_id=light.нет_такого")

        assert response.json() == [], response.text


class TestBehaviorsUpdate:
    """Правка поведений устройства."""

    def test_should_accept_valid_params(self, isolated_client: TestClient) -> None:
        """Корректные параметры сохраняются.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        device = _make_device(isolated_client)

        response = isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={
                "behaviors": [
                    {"template": "lighting", "priority": 10, "params": {"brightness": 200}}
                ]
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["behaviors"][0]["params"] == {"brightness": 200}
        assert body["inert_params"] == [], response.text

        # Ответ и список устройства обязаны совпадать: форма заполняется из
        # ответа, список — источник истины. Расхождение означало бы, что одно
        # из двух показывает пользователю не то, что сохранено.
        #
        # Граница этой проверки, проверенная инъекцией: замена чтения из манифеста
        # на эхо запроса эту проверку НЕ роняет, потому что манифест сейчас
        # ничего не нормализует — сохранённое в точности равно присланному.
        # Отличие проявится, только если сервис начнёт дополнять умолчания или
        # отбрасывать пустые значения. Считать различие доказанным нельзя.
        listing = isolated_client.get("/api/v1/devices?ha_entity_id=light.behavior_probe")
        assert listing.json()[0]["behaviors"] == body["behaviors"], (
            "ответ правки и список устройств расходятся: форма показала бы не то, что сохранено"
        )

    def test_should_reject_unknown_param_with_layer_in_message(
        self, isolated_client: TestClient
    ) -> None:
        """Неизвестный параметр отвергается, и в тексте назван слой.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        device = _make_device(isolated_client)

        response = isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={
                "behaviors": [
                    {"template": "lighting", "priority": 10, "params": {"не_существует": 1}}
                ]
            },
        )

        assert response.status_code == 400, response.text
        assert "слой 1" in response.text, response.text

    def test_should_reject_out_of_range_value(self, isolated_client: TestClient) -> None:
        """Значение вне диапазона отвергается.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        device = _make_device(isolated_client)

        response = isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={
                "behaviors": [
                    {"template": "lighting", "priority": 10, "params": {"brightness": 300}}
                ]
            },
        )

        assert response.status_code == 400, response.text
        assert "слой 3" in response.text, response.text

    def test_should_accept_now_working_climate_param(self, isolated_client: TestClient) -> None:
        """Гистерезис климата сохраняется как действующий и не попадает в замечания.

        Проверка переписана 2026-10-09. Раньше она утверждала, что `hysteresis`
        инертен, и требовала видеть его в `inert_params` — тогда это было правдой:
        параметр читался только валидатором. Теперь его читает условие обогрева,
        и если бы он остался в замечаниях, владелец видел бы действующую
        настройку как «ни на что не влияет» и счёл бы платформу сломанной.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        device = _make_device(isolated_client)

        response = isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={
                "behaviors": [
                    {
                        "template": "climate_control",
                        "priority": 10,
                        "params": {"hysteresis": 0.5},
                    }
                ]
            },
        )

        assert response.status_code == 200, response.text
        assert "hysteresis" not in response.json()["inert_params"], (
            "гистерезис читается условием may_heat и работает: попадание в "
            "inert_params сказало бы владельцу, что настройка пустая"
        )

    def test_should_reject_unknown_template(self, isolated_client: TestClient) -> None:
        """Поведение на несуществующем шаблоне отвергается.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        device = _make_device(isolated_client)

        response = isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={"behaviors": [{"template": "нет_такого", "priority": 10, "params": {}}]},
        )

        assert response.status_code == 400, response.text
        assert "слой 5" in response.text, response.text

    def test_should_not_change_behavior_on_rejected_params(
        self, isolated_client: TestClient
    ) -> None:
        """Отказ не оставляет устройство в промежуточном состоянии.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        device = _make_device(isolated_client)
        isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={
                "behaviors": [
                    {"template": "lighting", "priority": 10, "params": {"brightness": 111}}
                ]
            },
        )

        rejected = isolated_client.put(
            f"/api/v1/devices/{device}/behaviors",
            json={
                "behaviors": [
                    {"template": "lighting", "priority": 10, "params": {"brightness": 999}}
                ]
            },
        )

        assert rejected.status_code == 400
        listing = isolated_client.get("/api/v1/devices?ha_entity_id=light.behavior_probe")
        saved = listing.json()[0]["behaviors"]
        assert [b["params"] for b in saved] == [{"brightness": 111}], (
            f"поведения изменились, хотя правка была отвергнута: {saved}. "
            "Значение сравнивается точно, а не «список непустой»: проверка на "
            "непустоту проходила и после записи отвергнутых параметров"
        )
