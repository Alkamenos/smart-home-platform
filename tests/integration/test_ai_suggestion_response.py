"""
Ответ на AI-предложение обязан менять запись в базе (FR-036).

Маршрут `/api/ai/suggestion/{id}/respond` отвечает `{"status": "success"}`,
поэтому проверять код ответа бессмысленно: именно при сломанной записи он был
200. Проверка идёт вторым соединением к той же SQLite — читается фактическая
строка `ai_suggestions`.

Место — `tests/integration/`, а не `tests/contract/`: здесь важна не форма
ответа HTTP, а совместная работа маршрута и хранилища. Соседние тесты
разделов журнала (`test_fsm_history_sections.py`) живут здесь же, а
`tests/test_webui.py:130` проверял лишь `status_code != 500` и на этот дефект
был зелёным.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.persistence.event_store import SUGGESTION_STATUSES


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Путь к отдельной базе журнала.

    Returns:
        Путь к файлу SQLite во временном каталоге.
    """
    return str(tmp_path / "history.db")


@pytest.fixture
def client(db_path: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Клиент приложения, чей маршрут подсказок пишет в отдельную базу."""
    from fastapi import FastAPI

    from core.persistence.event_store import EventStore
    from webui import routes

    monkeypatch.setattr(routes, "event_store", EventStore(db_path=db_path))
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, headers=ADMIN)


def read_row(db_path: str, suggestion_id: int) -> tuple[str | None, float | None, float | None]:
    """Прочитать статус и отметки времени предложения из базы.

    Соединение открывается здесь, а не берётся из хранилища, чтобы проверка
    опиралась на то, что действительно лежит на диске.

    Args:
        db_path: Путь к файлу SQLite.
        suggestion_id: Идентификатор предложения.

    Returns:
        Кортеж ``(status, applied_at, dismissed_at)``.
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, applied_at, dismissed_at FROM ai_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"предложения {suggestion_id} нет в базе"
    return row[0], row[1], row[2]


@pytest.fixture
def suggestion_id(client: TestClient, db_path: str) -> int:
    """Посеять предложение в статусе pending.

    Args:
        client: Клиент приложения.
        db_path: Путь к файлу SQLite.

    Returns:
        Идентификатор посеянного предложения.
    """
    from core.persistence.event_store import EventStore

    suggestion_id = EventStore(db_path=db_path).save_ai_suggestion(
        suggestion_type="optimization",
        title="Отключить свет на кухне",
        description="Никого нет дома час",
        affected_entities=["light.kitchen"],
        proposed_changes={"brightness": 0},
    )
    assert read_row(db_path, suggestion_id)[0] == "pending"
    return suggestion_id


class TestSuggestionResponse:
    """Решение пользователя записывается в базу."""

    def test_should_mark_suggestion_applied_when_accepted(
        self, client: TestClient, db_path: str, suggestion_id: int
    ) -> None:
        """Принятие помечает предложение как applied с отметкой времени."""
        response = client.post(
            f"/api/ai/suggestion/{suggestion_id}/respond", json={"action": "accept"}
        )

        assert response.status_code == 200
        status, applied_at, dismissed_at = read_row(db_path, suggestion_id)
        assert status == "applied"
        assert applied_at is not None
        assert dismissed_at is None

    def test_should_mark_suggestion_dismissed_when_rejected(
        self, client: TestClient, db_path: str, suggestion_id: int
    ) -> None:
        """Отклонение помечает предложение как dismissed с отметкой времени."""
        response = client.post(
            f"/api/ai/suggestion/{suggestion_id}/respond", json={"action": "reject"}
        )

        assert response.status_code == 200
        status, applied_at, dismissed_at = read_row(db_path, suggestion_id)
        assert status == "dismissed"
        assert dismissed_at is not None
        assert applied_at is None

    def test_should_stop_listing_decided_suggestion_as_pending(
        self, client: TestClient, suggestion_id: int
    ) -> None:
        """Решённое предложение исчезает из раздела ожидающих."""
        client.post(f"/api/ai/suggestion/{suggestion_id}/respond", json={"action": "accept"})

        body = client.get("/api/ai/suggestions").json()

        assert [item["id"] for item in body["suggestions"]] == []


class TestSuggestionStatusVocabulary:
    """Словарь статусов хранилища: прежние три работают, чужой — ошибка."""

    def test_should_keep_writing_every_storage_status(
        self, db_path: str, suggestion_id: int
    ) -> None:
        """applied/dismissed/snoozed записываются в столбец status как есть."""
        from core.persistence.event_store import EventStore

        store = EventStore(db_path=db_path)

        for status in sorted(SUGGESTION_STATUSES):
            store.update_suggestion_status(suggestion_id, status)
            assert read_row(db_path, suggestion_id)[0] == status

    def test_should_reject_unknown_status(self, db_path: str, suggestion_id: int) -> None:
        """Статус вне словаря поднимает ошибку, а не молча не пишет ничего."""
        from core.persistence.event_store import EventStore

        store = EventStore(db_path=db_path)

        with pytest.raises(ValueError, match="Неизвестный статус"):
            store.update_suggestion_status(suggestion_id, "accepted")

        assert read_row(db_path, suggestion_id)[0] == "pending"
