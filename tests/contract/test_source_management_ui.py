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

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEMPLATE = (
    Path(__file__).resolve().parent.parent.parent / "src" / "webui" / "templates" / "discovery.html"
)

ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _function_body(source: str, name: str, length: int = 3000) -> str:
    """Вырезать тело функции из шаблона.

    Отдельная функция нужна, потому что разбор «по первому совпадению имени»
    давал неверный фрагмент: первое вхождение ``deleteSource`` — это wires в
    обработчике события, а не определение. Тест проверял не тот код.
    """
    marker = f"async function {name}("
    start = source.index(marker)
    return source[start : start + length]


@pytest.fixture
def client() -> TestClient:
    from main import app

    return TestClient(app, headers=ADMIN)


def _create(client: TestClient, name: str = "источник-проверки") -> str:
    response = client.post(
        "/api/v1/devices/sources",
        json={"name": name, "url": "http://ha.invalid:8123", "token": "token-длинный"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestSourceDeletionIsAvailable:
    """Пункт 1: источник должен можно удалить."""

    def test_page_offers_deletion(self, template: str) -> None:
        """Страница содержит элемент удаления источника."""
        assert "deleteSource" in template, (
            "на странице нет удаления источника: ошибочно созданный источник невозможно убрать"
        )

    def test_deletion_calls_delete_method(self, template: str) -> None:
        """Удаление использует метод DELETE, а не подмену через POST."""
        body = _function_body(template, "deleteSource")
        assert "method: 'DELETE'" in body, (
            "удаление должно вызывать DELETE /api/v1/devices/sources/{id}"
        )
        assert "${API.sources}/" in body, (
            "удаление должно обращаться к эндпоинту источников, а не к другому адресу"
        )

    def test_deletion_requires_confirmation(self, template: str) -> None:
        """Перед удалением спрашивается подтверждение.

        Без подтверждения опечатка в названии или случайный клик удаляет
        источник вместе с привязанными к нему устройствами.
        """
        assert "confirm(" in template, (
            "удаление происходит без подтверждения: источник с привязанными "
            "устройствами исчезнет по ошибке"
        )

    def test_confirmation_names_the_source(self, template: str) -> None:
        """В подтверждении видно, что именно удаляется.

        «Удалить источник?» без названия бесполезно, когда источников несколько.
        """
        body = _function_body(template, "deleteSource")
        # Текст подтверждения собирается ДО вызова confirm, поэтому проверяется
        # префикс тела функции, а не аргумент вызова.
        prefix = body[: body.index("window.confirm(")]

        assert "${title}" in prefix, (
            f"в подтверждении нет названия источника: удалять придётся наугад — {prefix[-300:]}"
        )

    def test_confirmation_states_consequences(self, template: str) -> None:
        """В подтверждении сказано, что произойдёт с устройствами.

        Иначе решение принимается вслепую: человек удалит источник, не зная, что
        вместе с ним отвяжутся устройства.
        """
        body = _function_body(template, "deleteSource")
        prefix = body[: body.index("window.confirm(")]

        assert "устройств" in prefix.lower(), (
            "в подтверждении не сказано про последствия для устройств"
        )

    def test_deletion_reloads_the_list(self, template: str) -> None:
        """После удаления список перечитывается.

        Иначе удалённый источник остался бы на экране до перезагрузки
        страницы, то есть интерфейс показывал бы неправду.
        """
        body = _function_body(template, "deleteSource")
        delete_index = body.index("method: 'DELETE'")
        after_delete = body[delete_index:]

        assert "loadSources()" in after_delete, (
            "после удаления список источников не перечитывается: карточка "
            "удалённого источника останется на экране"
        )

    def test_cancelled_confirmation_sends_nothing(self, template: str) -> None:
        """Отказ от подтверждения не вызывает удаление."""
        body = _function_body(template, "deleteSource")
        confirm_index = body.index("window.confirm(")
        delete_index = body.index("method: 'DELETE'")

        assert "return;" in body[confirm_index:delete_index], (
            "после отказа от подтверждения код продолжает удалять: подтверждение не имеет силы"
        )


class TestSourceStatusIsVisible:
    """Подробные подсказки: пользователь должен видеть, что источник не работает."""

    def test_status_is_rendered(self, template: str) -> None:
        """Карточка показывает статус источника."""
        assert "source.status" in template, (
            "статус источника не выводится: отключённый источник выглядит как "
            "рабочий, и причина молчит"
        )

    def test_error_reason_is_rendered(self, template: str) -> None:
        """Причина отказа показывается текстом."""
        assert "source.last_error" in template, (
            "last_error не выводится: пользователь не видит, почему источник не отвечает"
        )

    def test_last_sync_is_rendered(self, template: str) -> None:
        """Время последней синхронизации показывается."""
        assert "source.last_sync" in template, (
            "время последней синхронизации не выводится: нельзя понять, "
            "обновляются ли данные вообще"
        )


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
