"""Persistent-уведомление: одно, по изменению и без спама."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.persistence.health_store import HealthStore
from core.services.health_notifier import NOTIFICATION_ID, HealthNotifier
from core.services.health_registry import HealthRegistry


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


class _Channel:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.created: list[tuple[str, str, str]] = []
        self.dismissed: list[str] = []

    async def create(self, title: str, message: str, notification_id: str) -> bool:
        """Запомнить создание.

        Args:
            title: Заголовок.
            message: Текст.
            notification_id: Идентификатор.

        Returns:
            Успех канала.
        """
        self.created.append((title, message, notification_id))
        return self.ok

    async def dismiss(self, notification_id: str) -> bool:
        """Запомнить снятие.

        Args:
            notification_id: Идентификатор.

        Returns:
            Успех канала.
        """
        self.dismissed.append(notification_id)
        return self.ok


def _problem(detail: str = "молчит 2 ч") -> dict:
    return {
        "kind": "stale",
        "subject": "sensor.x",
        "name": "Датчик",
        "area": "Спальня",
        "detail": detail,
    }


def _notifier(tmp_path, channel: _Channel, clock: _Clock) -> HealthNotifier:
    registry = HealthRegistry(HealthStore(tmp_path / "health.json"), clock=lambda: NOW)
    return HealthNotifier(
        create=channel.create,
        dismiss=channel.dismiss,
        registry=registry,
        repeat_hours=24,
        clock=clock,
    )


@pytest.mark.asyncio
async def test_new_problem_creates_notification(tmp_path) -> None:
    """Появилась проблема — одно уведомление со сводкой."""
    channel = _Channel()
    notifier = _notifier(tmp_path, channel, _Clock(NOW))

    state = await notifier.publish({"count": 1, "problems": [_problem()]})

    assert len(channel.created) == 1
    assert channel.created[0][2] == NOTIFICATION_ID
    assert "Проблемы дома: 1" in channel.created[0][0]
    assert state["active"] is True


@pytest.mark.asyncio
async def test_same_set_is_silent(tmp_path) -> None:
    """Тот же состав — повторного уведомления нет."""
    channel = _Channel()
    clock = _Clock(NOW)
    notifier = _notifier(tmp_path, channel, clock)
    report = {"count": 1, "problems": [_problem()]}
    await notifier.publish(report)

    clock.moment = NOW + timedelta(hours=1)
    await notifier.publish(report)

    assert len(channel.created) == 1


@pytest.mark.asyncio
async def test_same_set_repeats_after_a_day(tmp_path) -> None:
    """Состав не менялся сутки — одно обновление."""
    channel = _Channel()
    clock = _Clock(NOW)
    notifier = _notifier(tmp_path, channel, clock)
    report = {"count": 1, "problems": [_problem()]}
    await notifier.publish(report)

    clock.moment = NOW + timedelta(hours=25)
    await notifier.publish(report)

    assert len(channel.created) == 2


@pytest.mark.asyncio
async def test_empty_problems_dismiss_notification(tmp_path) -> None:
    """Проблем нет — уведомление снято."""
    channel = _Channel()
    notifier = _notifier(tmp_path, channel, _Clock(NOW))
    await notifier.publish({"count": 1, "problems": [_problem()]})

    state = await notifier.publish({"count": 0, "problems": []})

    assert channel.dismissed == [NOTIFICATION_ID]
    assert state["active"] is False


@pytest.mark.asyncio
async def test_failed_send_is_dirty_and_retried(tmp_path) -> None:
    """Home Assistant не подтвердил — состояние dirty, следующий обход повторяет."""
    channel = _Channel(ok=False)
    clock = _Clock(NOW)
    notifier = _notifier(tmp_path, channel, clock)
    report = {"count": 1, "problems": [_problem()]}

    state = await notifier.publish(report)
    assert state["dirty"] is True

    channel.ok = True
    clock.moment = NOW + timedelta(minutes=1)
    state = await notifier.publish(report)

    assert state["dirty"] is False
    assert len(channel.created) == 2


@pytest.mark.asyncio
async def test_restart_does_not_repeat_same_notification(tmp_path) -> None:
    """После перезапуска тот же состав не отправляется заново."""
    channel = _Channel()
    clock = _Clock(NOW)
    report = {"count": 1, "problems": [_problem()]}
    await _notifier(tmp_path, channel, clock).publish(report)

    restarted = _notifier(tmp_path, channel, clock)
    await restarted.publish(report)

    assert len(channel.created) == 1
