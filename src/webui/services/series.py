"""История показаний локации для мини-графиков (спека 017, US1).

Sparkline нужна короткая история чисел: «как менялась температура за последние
часы». Берётся она из того же журнала событий, что и история локации, — отдельное
хранилище не заводится. Битовые роли (движение, контакт, дождь) сводятся к 0/1,
чтобы их тоже можно было нарисовать линией.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


#: Роли, для которых строится график.
SERIES_ROLES = frozenset(
    {
        "temperature",
        "humidity",
        "illuminance",
        "lux",
        "pressure",
        "wind",
        "uv",
        "co2",
        "power",
        "battery",
        "soil_moisture",
        "soil_conductivity",
        "motion",
        "contact",
        "rain",
    }
)

#: Сколько точек отдаётся по умолчанию.
DEFAULT_POINTS = 40

#: Значения битовых ролей, означающие «включено».
_ON_VALUES = frozenset({"on", "true", "1", "open", "opened", "detected", "wet"})


def _to_number(value: Any) -> float | None:
    """Преобразовать состояние в число для графика.

    Args:
        value: Состояние из журнала.

    Returns:
        Число либо ``None``, если значение не числовое и не битовое.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _ON_VALUES:
        return 1.0
    if text in {"off", "false", "0", "closed", "clear", "dry"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def build_series(
    event_store: Any,
    service: Any,
    location_id: str,
    *,
    points: int = DEFAULT_POINTS,
) -> dict[str, list[dict[str, Any]]]:
    """Собрать историю показаний локации по ролям.

    Args:
        event_store: Хранилище журнала событий.
        service: Наблюдение за локациями (роли и сущности).
        location_id: Идентификатор локации.
        points: Сколько последних точек вернуть на роль.

    Returns:
        Роль → список точек ``{at, value}`` в порядке времени.
    """
    if event_store is None or service is None:
        return {}
    sensor_entities = getattr(service, "sensor_entities", None)
    role_of = getattr(service, "role_of", None)
    if not callable(sensor_entities) or not callable(role_of):
        # Наблюдение не собрано полностью: лучше без графиков, чем 500 на обзор.
        return {}
    entities = sensor_entities(location_id)
    if not entities:
        return {}

    events = event_store.get_events_for_entities(entities, limit=points * 4)
    by_role: dict[str, list[dict[str, Any]]] = {}
    for event in sorted(events, key=lambda item: item.timestamp or 0):
        role = role_of(location_id, event.entity_id)
        if role not in SERIES_ROLES:
            continue
        value = _to_number(event.new_state)
        if value is None:
            continue
        at = datetime.fromtimestamp(event.timestamp or 0, tz=UTC).isoformat()
        bucket = by_role.setdefault(role, [])
        bucket.append({"at": at, "value": value})
        if len(bucket) > points:
            del bucket[0]
    return by_role
