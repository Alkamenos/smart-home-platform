"""Ожидаемый интервал: история событий и запасной вариант по классу."""

from __future__ import annotations

from core.services.health_expectations import BATTERY_STALE_SEC, HealthExpectations


NOW = 1_800_000_000.0


class _Events:
    """Хранилище-двойник с готовыми метками."""

    def __init__(self, timestamps: list[float]) -> None:
        self.timestamps = timestamps
        self.calls = 0

    def event_timestamps_since(self, entity_id: str, since_ts: float) -> list[float]:
        """Отдать метки после порога.

        Args:
            entity_id: Сущность.
            since_ts: Начало периода.

        Returns:
            Отфильтрованные метки.
        """
        self.calls += 1
        return [value for value in self.timestamps if value >= since_ts]


def _history(interval_sec: float, count: int = 10) -> list[float]:
    return [NOW - interval_sec * index for index in range(count)]


def test_history_median_sets_interval_and_threshold() -> None:
    """Медиана истории задаёт интервал, порог не меньше двух часов."""
    store = _Events(_history(600))
    service = HealthExpectations(event_store=store, clock=lambda: NOW)

    expectation = service.expectation("sensor.temperature", "temperature", NOW)

    assert expectation.source == "history"
    assert expectation.expected_interval_sec == 600
    assert expectation.stale_after_sec == 7200
    assert expectation.samples == 9


def test_empty_history_uses_class_default() -> None:
    """Без истории берётся значение по классу."""
    service = HealthExpectations(event_store=_Events([]), clock=lambda: NOW)

    expectation = service.expectation("sensor.temperature", "temperature", NOW)

    assert expectation.source == "class"
    assert expectation.expected_interval_sec == 900
    assert expectation.stale_after_sec == 7200


def test_battery_has_its_own_daily_threshold() -> None:
    """Батарейка: сутки в ожидании, двое суток до тревоги."""
    service = HealthExpectations(clock=lambda: NOW)

    expectation = service.expectation("sensor.battery", "battery", NOW)

    assert expectation.expected_interval_sec == 86400
    assert expectation.stale_after_sec == BATTERY_STALE_SEC == 172800


def test_long_interval_raises_threshold_above_two_hours() -> None:
    """Редкий датчик (раз в 4 часа) не объявляется молчащим через 2 часа."""
    service = HealthExpectations(event_store=_Events(_history(4 * 3600)), clock=lambda: NOW)

    expectation = service.expectation("sensor.rare", "temperature", NOW)

    assert expectation.stale_after_sec == 8 * 3600


def test_cache_avoids_repeated_history_reads() -> None:
    """Повторный запрос в пределах часа не читает историю снова."""
    store = _Events(_history(600))
    service = HealthExpectations(event_store=store, clock=lambda: NOW)

    first = service.expectation("sensor.temperature", "temperature", NOW)
    second = service.expectation("sensor.temperature", "temperature", NOW + 60)

    assert first == second
    assert store.calls == 1
