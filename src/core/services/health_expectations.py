"""Ожидаемый интервал датчика: история событий плюс разумный запас.

Фиксированный порог «молчит 6 часов» не различает датчик, который шлёт
показания каждую минуту, и датчик, который отчитывается раз в четыре часа.
Служба здоровья спрашивает историю (`history.db`), считает медиану интервалов
за неделю и только при недостатке данных берёт значение по классу прибора.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

from core.models.health import SensorExpectation


#: Типичные интервалы по классу прибора, секунды.
CLASS_INTERVALS: dict[str, float] = {
    "temperature": 15 * 60,
    "humidity": 15 * 60,
    "illuminance": 15 * 60,
    "pressure": 15 * 60,
    "carbon_dioxide": 15 * 60,
    "pm25": 15 * 60,
    "wind_speed": 30 * 60,
    "rain": 30 * 60,
    "soil_moisture": 30 * 60,
    "water": 30 * 60,
    "battery": 24 * 3600,
    "motion": 24 * 3600,
    "occupancy": 24 * 3600,
    "presence": 24 * 3600,
    "contact": 24 * 3600,
    "door": 24 * 3600,
    "window": 24 * 3600,
    "smoke": 24 * 3600,
    "gas": 24 * 3600,
}

#: Интервал, если класс незнаком.
DEFAULT_INTERVAL_SEC = 15 * 60

#: Порог молчания батарейки: она отчитывается раз в сутки, значит двое — уже много.
BATTERY_STALE_SEC = 48 * 3600

#: Минимальный порог молчания: даже самый частый датчик не объявляем молчащим
#: через минуту.
DEFAULT_STALE_MIN_SEC = 2 * 3600

#: Сколько секунд держать рассчитанное ожидание в памяти.
CACHE_TTL_SEC = 3600

#: Минимум интервалов, чтобы считать историю достаточной.
MIN_SAMPLES = 3


class HealthExpectations:
    """Считать ожидаемый интервал и порог молчания для датчиков.

    Args:
        event_store: Хранилище истории; нужен метод ``event_timestamps_since``.
        window_days: Окно истории в днях.
        stale_min_sec: Минимальный порог молчания.
        clock: Источник времени; подменяется в тестах.
    """

    def __init__(
        self,
        event_store: Any | None = None,
        window_days: int = 7,
        stale_min_sec: float = DEFAULT_STALE_MIN_SEC,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._event_store = event_store
        self._window_sec = max(1, window_days) * 24 * 3600
        self._stale_min_sec = max(0.0, stale_min_sec)
        self._clock = clock or time.time
        self._cache: dict[str, tuple[float, SensorExpectation]] = {}

    def expectation(
        self, entity_id: str, device_class: str | None, now_ts: float | None = None
    ) -> SensorExpectation:
        """Ожидание по датчику.

        Args:
            entity_id: Сущность.
            device_class: Класс прибора из Home Assistant.
            now_ts: Текущее время Unix; по умолчанию системное.

        Returns:
            Ожидание с интервалом, порогом и источником.
        """
        now = self._clock() if now_ts is None else now_ts
        key = f"{entity_id}|{str(device_class or '').lower()}"
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < CACHE_TTL_SEC:
            return cached[1]
        expectation = self._compute(entity_id, device_class, now)
        self._cache[key] = (now, expectation)
        return expectation

    def _compute(
        self, entity_id: str, device_class: str | None, now_ts: float
    ) -> SensorExpectation:
        """Рассчитать ожидание без кэша.

        Args:
            entity_id: Сущность.
            device_class: Класс прибора.
            now_ts: Текущее время.

        Returns:
            Ожидание.
        """
        value = str(device_class or "").lower()
        if value == "battery":
            return SensorExpectation(
                entity_id=entity_id,
                expected_interval_sec=float(CLASS_INTERVALS["battery"]),
                stale_after_sec=float(BATTERY_STALE_SEC),
                source="class",
            )
        timestamps = self._timestamps(entity_id, now_ts)
        if len(timestamps) >= MIN_SAMPLES + 1:
            intervals = [
                later - earlier
                for earlier, later in zip(timestamps, timestamps[1:], strict=False)
                if later > earlier
            ]
            if len(intervals) >= MIN_SAMPLES:
                interval = float(statistics.median(intervals))
                return SensorExpectation(
                    entity_id=entity_id,
                    expected_interval_sec=interval,
                    stale_after_sec=max(2 * interval, self._stale_min_sec),
                    source="history",
                    samples=len(intervals),
                )
        interval = float(CLASS_INTERVALS.get(value, DEFAULT_INTERVAL_SEC))
        return SensorExpectation(
            entity_id=entity_id,
            expected_interval_sec=interval,
            stale_after_sec=max(2 * interval, self._stale_min_sec),
            source="class",
        )

    def _timestamps(self, entity_id: str, now_ts: float) -> list[float]:
        """Прочитать времена событий из хранилища.

        Args:
            entity_id: Сущность.
            now_ts: Текущее время.

        Returns:
            Отсортированные метки; пустой список при отсутствии истории.
        """
        store = self._event_store
        reader = getattr(store, "event_timestamps_since", None)
        if not callable(reader):
            return []
        try:
            values = reader(entity_id, now_ts - self._window_sec)
        except Exception:  # noqa: BLE001 — история не должна ронять обход
            return []
        return sorted(float(value) for value in values or [])

    def clear_cache(self) -> None:
        """Сбросить кэш (например, после изменения истории).

        Returns:
            Ничего.
        """
        self._cache.clear()
