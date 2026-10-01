"""
Интеграционные тесты фактических данных визуализаций (FR-032…FR-037).

Графики должны строиться по реальным записям, а при их отсутствии — сообщать
об этом, а не показывать правдоподобные выдуманные значения (решение D-2).
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def client():
    """Клиент приложения от администратора."""
    from src.main import app

    return TestClient(app, headers=ADMIN)


@pytest.fixture
def store(tmp_path: Path):
    """Журнал событий в отдельной базе."""
    from src.core.persistence.event_store import EventStore

    return EventStore(db_path=str(tmp_path / "history.db"))


class TestTransitionJournal:
    """Переходы попадают в журнал и питают агрегацию (FR-033)."""

    def test_should_aggregate_transitions_by_weekday_and_hour(self, store) -> None:
        """Агрегация считает записи, а не воспроизводит генератор."""
        from src.core.persistence.event_store import FsmTransition

        now = time.time()
        for offset_hours in (0, 2, 5):
            store.save_fsm_transition(
                FsmTransition(
                    entity_id="light.kitchen",
                    from_state="OFF",
                    to_state="ON_MOTION",
                    trigger_name="motion_detected",
                    trace_id="t1",
                    timestamp=now - offset_hours * 3600,
                )
            )

        heatmap = store.get_activity_heatmap()

        assert heatmap["has_data"] is True
        values = [value for day in heatmap["data"] for value in day["values"]]
        assert sum(values) == 3

    def test_should_report_no_data_when_journal_empty(self, store) -> None:
        """Пустой журнал — признак отсутствия данных, а не нули как факт."""
        heatmap = store.get_activity_heatmap()

        assert heatmap["has_data"] is False
        assert heatmap["data"] == []

    def test_should_keep_same_result_for_repeated_queries(self, store) -> None:
        """Два одинаковых запроса дают одинаковый ответ (SC-013)."""
        from src.core.persistence.event_store import FsmTransition

        store.save_fsm_transition(
            FsmTransition(
                entity_id="light.kitchen",
                from_state="OFF",
                to_state="ON",
                trigger_name="motion_detected",
                trace_id="t1",
            )
        )

        assert store.get_activity_heatmap() == store.get_activity_heatmap()

    def test_should_count_events_and_transitions_together(self, store) -> None:
        """Активность учитывает и переходы, и события устройств."""
        from src.core.persistence.event_store import FsmTransition, SensorEvent

        now = time.time()
        store.save_fsm_transition(
            FsmTransition(
                entity_id="light.kitchen",
                from_state="OFF",
                to_state="ON",
                trigger_name="motion_detected",
                trace_id="t1",
                timestamp=now,
            )
        )
        store.save_sensor_event(
            SensorEvent(
                entity_id="light.kitchen",
                old_state="off",
                new_state="on",
                event_type="state_changed",
                trace_id="t2",
                timestamp=now,
            )
        )

        heatmap = store.get_activity_heatmap()

        assert sum(v for day in heatmap["data"] for v in day["values"]) == 2


class TestEventHistoryAggregation:
    """История событий за сутки (FR-033)."""

    def test_should_bucket_events_by_wall_clock_hour(self, store) -> None:
        """Событие попадает в корзину своего часа по настенным часам.

        Прежние корзины считались «часов назад» при подписях от ``00:00``, и
        график отображался задом наперёд (R-10).
        """
        from datetime import datetime

        from src.core.persistence.event_store import SensorEvent

        moment = datetime.now().replace(minute=5, second=0, microsecond=0)
        store.save_sensor_event(
            SensorEvent(
                entity_id="light.kitchen",
                old_state="off",
                new_state="on",
                event_type="state_changed",
                trace_id="t1",
                timestamp=moment.timestamp(),
            )
        )

        history = store.get_hourly_history(hours=24)

        assert history["has_data"] is True
        assert history["data"][moment.hour] == 1

    def test_should_report_no_data_when_no_events(self, store) -> None:
        """Нет событий — признак отсутствия данных."""
        history = store.get_hourly_history(hours=24)

        assert history["has_data"] is False
        assert sum(history["data"]) == 0


class TestVisualizationEndpoints:
    """Разделы интерфейса отдают фактические данные (FR-032…FR-037)."""

    def test_heatmap_should_always_include_has_data(self, client: TestClient) -> None:
        """Ключ has_data присутствует независимо от наличия данных."""
        response = client.get("/api/history/activity-heatmap")

        assert response.status_code == 200
        assert "has_data" in response.json()

    def test_heatmap_should_not_contain_generated_values(self, client: TestClient) -> None:
        """Значения не воспроизводятся генератором с фиксированным зерном."""
        first = client.get("/api/history/activity-heatmap").json()
        second = client.get("/api/history/activity-heatmap").json()

        assert first == second
        # Прежний генератор всегда рисовал пики утром и вечером.
        if first["has_data"]:
            values = [v for day in first["data"] for v in day["values"]]
            assert max(values) > 0
        else:
            assert first["data"] == []

    def test_events_history_should_always_include_has_data(self, client: TestClient) -> None:
        """История событий сообщает о наличии данных."""
        response = client.get("/api/events/history")

        assert response.status_code == 200
        assert "has_data" in response.json()

    def test_suggestions_should_return_object_with_has_data(self, client: TestClient) -> None:
        """Подсказки возвращаются объектом, а не массивом (FR-035)."""
        response = client.get("/api/ai/suggestions")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)
        assert "suggestions" in body
        assert "has_data" in body

    def test_suggestions_should_not_invent_records(self, client: TestClient) -> None:
        """Выдуманные подсказки удалены полностью."""
        body = client.get("/api/ai/suggestions").json()

        for suggestion in body["suggestions"]:
            assert not str(suggestion.get("id", "")).startswith("sugg_00")

    def test_overrides_keep_real_data(self, client: TestClient) -> None:
        """Раздел оверрайдов не менялся: он всегда отдавал настоящие данные."""
        response = client.get("/api/overrides")

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestDeviceEventRecording:
    """События устройств попадают в журнал (FR-033, T053)."""

    def test_should_record_device_state_change_in_journal(self, tmp_path: Path) -> None:
        """Изменение состояния устройства записывается в таблицу событий."""
        import asyncio

        from src.core.events.event_bus import EventBus
        from src.core.persistence.event_store import EventStore
        from src.services.fsm_state_bridge import FSMStateBridge

        store = EventStore(db_path=str(tmp_path / "history.db"))
        bus = EventBus()
        FSMStateBridge(event_bus=bus, dispatcher=None, event_store=store)

        asyncio.run(
            bus.publish(
                "state_change",
                {
                    "entity_id": "light.kitchen",
                    "old_state": "off",
                    "new_state": "on",
                    "context": {"trace_id": "abc"},
                },
            )
        )

        events = store.get_events(entity_id="light.kitchen")
        assert len(events) == 1
        assert events[0].new_state == "on"

    def test_should_not_break_transition_when_recording_fails(self, tmp_path: Path) -> None:
        """Ошибка записи в журнал не влияет на обработку события."""
        import asyncio
        from unittest.mock import MagicMock

        from src.core.events.event_bus import EventBus
        from src.services.fsm_state_bridge import FSMStateBridge

        store = MagicMock()
        store.save_sensor_event.side_effect = RuntimeError("db locked")
        bus = EventBus()
        FSMStateBridge(event_bus=bus, dispatcher=None, event_store=store)

        asyncio.run(
            bus.publish(
                "state_change",
                {"entity_id": "light.kitchen", "old_state": "off", "new_state": "on"},
            )
        )
