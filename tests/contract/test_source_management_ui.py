"""Источники: удаление из интерфейса и видимый статус.

Пункт 1 плана работы над веб-интерфейсом: «я как пользователь хочу добавлять и
удалять источники устройств, при этом должна быть валидация и подробные
подсказки».

Что уже было и что не хватало
------------------------------
Создание источника реализовано: форма `source-form` с полями `name`, `url`,
`token`, разбор ответа 422 по полям через `showSourceFormErrors`. Это в порядке
и не переписывается.

Не хватало двух вещей:

1. **Удаления не было вовсе.** В шаблоне ноль вхождений удаления; карточка
   источника — это `<div>` без кнопок. Пользователь мог создать источник, но не
   мог его убрать, то есть ошибочно созданный источник оставался навсегда.
2. **Статус источника не показывался.** `SourceResponse` содержит `status`,
   `last_sync` и `last_error`, но карточка выводила только название и адрес.
   Отключённый источник с ошибкой выглядел ровно как рабочий — при том, что
   именно эта ошибка объясняет, почему устройства не добавляются.

Проверяется поведение страницы, а не наличие слов: удаление должно вызывать
`DELETE`, требовать подтверждения и показывать причину отказа. Ответ API
проверяется отдельно, потому что интерфейс опирается на его контракт.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import pytest
from fastapi.testclient import TestClient


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app, headers=ADMIN)


def _create(client: TestClient, name: str = "источник-проверки") -> str:
    """Создать источник каноническим путём.

    Args:
        client: Тестовый клиент.
        name: Имя источника.

    Returns:
        Идентификатор созданного источника.
    """
    response = client.post(
        "/api/v1/devices/sources",
        json={"name": name, "url": "http://ha.invalid:8123", "token": "token-длинный"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestDeletionApiContract:
    """Интерфейс опирается на контракт удаления — он проверяется отдельно."""

    def test_delete_removes_source(self, client: TestClient) -> None:
        """Удалённый источник исчезает из списка."""
        source_id = _create(client)

        response = client.delete(f"/api/v1/devices/sources/{source_id}")

        assert response.status_code == 204
        remaining = {s["id"] for s in client.get("/api/v1/devices/sources").json()}
        assert source_id not in remaining, "источник остался в списке после удаления"

    def test_delete_unknown_returns_404(self, client: TestClient) -> None:
        """Несуществующий источник — 404, а не 204."""
        response = client.delete("/api/v1/devices/sources/00000000-0000-0000-0000-000000000000")

        assert response.status_code == 404, (
            "удаление несуществующего источника должно сообщать 404: иначе "
            "интерфейс сочтёт операцию успешной"
        )

    def test_delete_twice_reports_not_found(self, client: TestClient) -> None:
        """Повторное удаление честно сообщает, что источника уже нет."""
        source_id = _create(client)
        assert client.delete(f"/api/v1/devices/sources/{source_id}").status_code == 204

        second = client.delete(f"/api/v1/devices/sources/{source_id}")

        assert second.status_code == 404, (
            "повторное удаление вернуло другой код: интерфейс не сможет отличить успех от неудачи"
        )

    def test_source_response_carries_status_fields(self, client: TestClient) -> None:
        """Ответ содержит поля, которые интерфейс показывает."""
        source_id = _create(client)

        payload = next(
            s for s in client.get("/api/v1/devices/sources").json() if s["id"] == source_id
        )

        for field in ("status", "last_sync", "last_error"):
            assert field in payload, (
                f"в ответе нет `{field}`: интерфейсу нечего показать по этому полю"
            )
        client.delete(f"/api/v1/devices/sources/{source_id}")


class TestSourceValidationMessages:
    """Подробные подсказки: ошибки должны быть конкретными."""

    @pytest.mark.parametrize(
        ("payload", "field"),
        [
            ({"name": "x", "url": "не-адрес", "token": "token-длинный"}, "url"),
            ({"name": "x", "url": "http://ha.invalid:8123", "token": "корот"}, "token"),
        ],
    )
    def test_invalid_field_is_named(
        self, client: TestClient, payload: dict[str, str], field: str
    ) -> None:
        """Ошибка приходит с указанием поля и текстом."""
        response = client.post("/api/v1/devices/sources", json=payload)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any(item["loc"][-1] == field for item in detail), (
            f"в ошибке нет имени поля `{field}`: показать подсказку не у чего — {detail}"
        )
        assert any(item.get("msg") for item in detail), "у ошибки нет текста подсказки"
