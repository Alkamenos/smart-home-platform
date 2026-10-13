"""При пустом списке источников платформа может создать источник сама.

Просьба владельца: «при отсутствии источника есть смысл подставлять значения из
`.env` и какое-нибудь default имя».

Зачем это нужно
---------------
Платформа уже подключается к Home Assistant по `HA_URL` и `HA_TOKEN` из
окружения — адаптер читает их при старте (`core/container.py`). Пользователю
приходится вводить в форму ровно то, что уже задано в `.env`, и он неизбежно
набирает это вручную или ошибается. В развёртывании это проявилось буквально:
источник с адресом `homeassistant.local` оказался нерабочим, потому что имя
не резолвится из контейнера, тогда как `HA_URL` в `.env` был верным.

Главное требование — безопасность
---------------------------------
**Токен не должен попадать в браузер.** Поэтому предлагается два разных
вызова: `GET` сообщает, что значения из окружения есть, и отдаёт только
несекретное (имя и адрес), а `POST` создаёт источник на сервере, где токен
достаётся из окружения и в ответ не возвращается.

Наивно отдавать токен в `GET`, чтобы предзаполнить поле формы, нельзя: значение
секрета окажется в HTML и в истории браузера.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import pytest
from fastapi.testclient import TestClient


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}
ENV_URL = "http://ha.example:8123"
ENV_TOKEN = "env-token-value-long-enough"


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app, headers=ADMIN)


@pytest.fixture
def env_configured(monkeypatch) -> None:
    monkeypatch.setenv("HA_URL", ENV_URL)
    monkeypatch.setenv("HA_TOKEN", ENV_TOKEN)


class TestSuggestionNeverLeaksToken:
    """Токен не должен покидать сервер."""

    def test_suggestion_omits_token(self, client: TestClient, env_configured: None) -> None:
        """В ответе с подсказкой токена нет."""
        response = client.get("/api/v1/devices/sources/from-env")

        assert response.status_code == 200
        assert ENV_TOKEN not in response.text, (
            "токен из окружения попал в ответ: секрет оказался в браузере и в истории запросов"
        )

    def test_suggestion_reports_token_presence_as_flag(
        self, client: TestClient, env_configured: None
    ) -> None:
        """Наличие токена сообщается флагом, а не самим значением."""
        body = client.get("/api/v1/devices/sources/from-env").json()

        assert body["has_token"] is True

    def test_created_source_omits_token(self, client: TestClient, env_configured: None) -> None:
        """Ответ создания тоже не содержит токен."""
        response = client.post("/api/v1/devices/sources/from-env")

        assert response.status_code == 201
        assert ENV_TOKEN not in response.text, "токен утёк в ответ создания источника"


class TestSuggestionContent:
    """Подсказка должна быть пригодной, а не формальной."""

    def test_provides_address_and_default_name(
        self, client: TestClient, env_configured: None
    ) -> None:
        """Адрес берётся из окружения, имя — осмысленное по умолчанию."""
        body = client.get("/api/v1/devices/sources/from-env").json()

        assert body["url"] == ENV_URL, f"адрес подсказки не из окружения: {body.get('url')}"
        assert body["name"], "имя источника должно быть, иначе поле останется пустым"

    def test_reports_availability(self, client: TestClient, env_configured: None) -> None:
        """Сказано, что значения есть."""
        body = client.get("/api/v1/devices/sources/from-env").json()

        assert body["available"] is True

    def test_reports_unavailable_without_token(self, client: TestClient, monkeypatch) -> None:
        """Без токена подсказка недоступна, а не ломает страницу."""
        monkeypatch.delenv("HA_TOKEN", raising=False)
        monkeypatch.setenv("HA_URL", ENV_URL)

        body = client.get("/api/v1/devices/sources/from-env").json()

        assert body["available"] is False
        assert body["has_token"] is False

    def test_reports_unavailable_without_url(self, client: TestClient, monkeypatch) -> None:
        """Без адреса подсказка недоступна."""
        monkeypatch.setenv("HA_TOKEN", ENV_TOKEN)
        monkeypatch.delenv("HA_URL", raising=False)

        body = client.get("/api/v1/devices/sources/from-env").json()

        assert body["available"] is False


class TestCreatingFromEnvironment:
    """Создание источника из окружения."""

    def test_creates_source_with_env_url(self, client: TestClient, env_configured: None) -> None:
        """Источник создаётся с адресом из окружения."""
        response = client.post("/api/v1/devices/sources/from-env")

        assert response.status_code == 201
        assert response.json()["url"].rstrip("/") == ENV_URL

    def test_created_source_appears_in_list(self, client: TestClient, env_configured: None) -> None:
        """Созданный источник виден в общем списке."""
        created = client.post("/api/v1/devices/sources/from-env").json()

        listed = {s["id"] for s in client.get("/api/v1/devices/sources").json()}

        assert created["id"] in listed

    def test_refuses_without_environment(self, client: TestClient, monkeypatch) -> None:
        """Без переменных окружения создание отклоняется понятной ошибкой."""
        monkeypatch.delenv("HA_TOKEN", raising=False)
        monkeypatch.delenv("HA_URL", raising=False)

        response = client.post("/api/v1/devices/sources/from-env")

        assert response.status_code in (409, 503), (
            f"без переменных окружения ожидался отказ, получен {response.status_code}"
        )

    def test_refuses_invalid_url_in_environment(self, client: TestClient, monkeypatch) -> None:
        """Неверный `HA_URL` даёт понятный отказ, а не 500 с текстом валидатора.

        Без предварительной проверки pydantic бросал бы `ValidationError` наружу,
        и оператор увидел бы внутреннюю ошибку вместо указания, что исправлять.
        """
        monkeypatch.setenv("HA_TOKEN", ENV_TOKEN)
        monkeypatch.setenv("HA_URL", "не-адрес")

        response = client.post("/api/v1/devices/sources/from-env")

        assert response.status_code == 409, (
            f"ожидался 409 с указанием на HA_URL, получен {response.status_code}"
        )
        assert "HA_URL" in response.json()["detail"]

    def test_requires_admin(self, env_configured: None) -> None:
        """Создание источника — операция администратора."""
        from main import app

        ordinary = TestClient(app, headers={"X-User-ID": "ordinary", "X-Is-Admin": "false"})

        response = ordinary.post("/api/v1/devices/sources/from-env")

        assert response.status_code == 403, (
            f"обычный пользователь получил {response.status_code} вместо 403: "
            "источник создаётся с токеном из окружения, это привилегия администратора"
        )
