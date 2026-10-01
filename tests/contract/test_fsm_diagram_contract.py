"""
Контрактные тесты формата диаграммы состояний (FR-029).

Диаграмма отдаётся чистой Mermaid-строкой: прежний JSON-конверт вставлялся в
страницу как текст, и пользователь видел `{"diagram": "stateDiagram-v2..."}`
вместо схемы.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Клиент приложения от администратора."""
    from src.main import app

    return TestClient(app, headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"})


class TestDiagramFormat:
    """GET /api/fsm/{entity_id}/diagram отдаёт Mermaid, а не JSON."""

    def test_should_return_plain_mermaid_when_requested(self, client: TestClient) -> None:
        """Тело ответа — Mermaid-строка, а не JSON-конверт."""
        response = client.get("/api/fsm/light.kitchen_lighting_10/diagram")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text.startswith("stateDiagram-v2")

    def test_should_not_wrap_diagram_in_json(self, client: TestClient) -> None:
        """Ответ не начинается с фигурной скобки (прежний дефект dashboard.html)."""
        response = client.get("/api/fsm/light.kitchen_lighting_10/diagram")

        assert not response.text.lstrip().startswith("{")

    def test_should_include_states_and_transitions(self, client: TestClient) -> None:
        """Диаграмма содержит состояния автомата и его переходы."""
        response = client.get("/api/fsm/light.kitchen_lighting_10/diagram")

        assert "ON_MOTION" in response.text
        assert "-->" in response.text

    def test_should_not_contain_current_state_marker(self, client: TestClient) -> None:
        """Текущее состояние не встраивается в схему: оно приходит отдельно."""
        response = client.get("/api/fsm/light.kitchen_lighting_10/diagram")

        assert "classDef current" not in response.text

    def test_return_404_for_unknown_fsm(self, client: TestClient) -> None:
        """Неизвестный автомат — 404 с описанием."""
        response = client.get("/api/fsm/light.absent_lighting_10/diagram")

        assert response.status_code == 404
        assert "error" in response.json()

    def test_return_503_when_platform_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Недоступная платформа — 503, а не пустая схема."""
        from src.main import app

        monkeypatch.setattr(app.state, "container", None, raising=False)

        response = client.get("/api/fsm/light.kitchen_lighting_10/diagram")

        assert response.status_code == 503
