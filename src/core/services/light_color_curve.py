"""Кривая глобальной цветовой температуры света: день → закат → 21:00 → ночь.

Чистая арифметика без Home Assistant: её проверяют отдельно от службы. Служба
читает границы и время заката, а формулу кривой берёт отсюда.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime, time, tzinfo
from typing import Any

from loguru import logger


#: Значения по умолчанию, если сущности «день/ночь» в доме не заданы.
DEFAULT_DAY_KELVIN = 6000.0
DEFAULT_NIGHT_KELVIN = 2000.0

#: Час, к которому свет становится максимально тёплым, если не задан в манифесте.
DEFAULT_WARM_AT = "21:00"

#: Границы, за которые расчёт не выходит: даже если сущности заданы странно.
MIN_KELVIN = 1000
MAX_KELVIN = 10000


def parse_hhmm(value: str | None, default: time) -> time:
    """Разобрать время ``HH:MM``.

    Args:
        value: Строка времени либо ``None``.
        default: Значение по умолчанию при ошибке.

    Returns:
        Время суток.
    """
    if not value:
        return default
    try:
        hours, minutes = value.strip().split(":", 1)
        return time(hour=int(hours), minute=int(minutes))
    except (TypeError, ValueError):
        logger.warning(f"Цветовая температура: не разобрано время {value!r} — беру {default}")
        return default


def parse_datetime(value: Any, tz: tzinfo) -> datetime | None:
    """Разобрать ISO-время из атрибутов ``sun.sun``.

    Args:
        value: Строка ISO 8601 либо ``None``.
        tz: Часовой пояс дома для значения без зоны.

    Returns:
        Время с зоной либо ``None``.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed


def target_kelvin(
    now: datetime,
    *,
    daylight: bool | None,
    sunset: datetime | None,
    day_kelvin: float,
    night_kelvin: float,
    warm_at: time,
) -> int:
    """Посчитать цветовую температуру на момент ``now``.

    Кривая: днём — ``day_kelvin``; после заката линейно к ``night_kelvin`` к
    ``warm_at``; после ``warm_at`` и до рассвета — ``night_kelvin``. Рассвет
    определяется состоянием солнца (``daylight = True``): отдельного плавного
    утреннего перехода нет — днём свет снова холодный.

    Если солнце неизвестно, остаётся время суток: 07:00–18:00 — день,
    18:00–``warm_at`` — плавное потепление, иначе ночь.

    Args:
        now: Текущее время в часовом поясе дома.
        daylight: Солнце над горизонтом; ``None`` — неизвестно.
        sunset: Время сегодняшнего заката; ``None`` — неизвестно.
        day_kelvin: Дневная граница, К.
        night_kelvin: Ночная граница, К.
        warm_at: Время максимального тепла.

    Returns:
        Целое значение в Кельвинах.
    """
    day = max(MIN_KELVIN, min(MAX_KELVIN, float(day_kelvin)))
    night = max(MIN_KELVIN, min(MAX_KELVIN, float(night_kelvin)))
    if daylight is True:
        return int(round(day))

    # ``sun.sun`` приходит из Home Assistant в UTC. Кривая же задаёт
    # ``warm_at`` по часам дома, поэтому закат приводим к поясу ``now``: иначе
    # 21:00 трактуется как 21:00 UTC и самое тёплое наступает в 02:00 по дому.
    if sunset is not None and now.tzinfo is not None:
        sunset = sunset.astimezone(now.tzinfo)

    if sunset is None:
        # Солнце не прочитано: грубая, но предсказуемая кривая по часам.
        if now.time() < time(7, 0):
            return int(round(night))
        sunset = datetime.combine(now.date(), time(18, 0), tzinfo=now.tzinfo)
        if now < sunset:
            return int(round(day))

    warm = datetime.combine(sunset.date(), warm_at, tzinfo=sunset.tzinfo)
    if now <= sunset:
        return int(round(day))
    if now >= warm:
        return int(round(night))
    span = (warm - sunset).total_seconds()
    if span <= 0:
        return int(round(night))
    fraction = (now - sunset).total_seconds() / span
    return int(round(day + (night - day) * fraction))
