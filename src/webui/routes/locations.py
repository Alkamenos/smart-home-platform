"""Состояние и история локаций по HTTP (спека 016, FR-007).

Снимок читается у наблюдения за локациями (``container.location_state``), а
история — из общего журнала событий: журнал локации это выборка по её датчикам,
и отдельного хранилища не заводится. Права — как у остальных чтений платформы:
это агрегированное наблюдение за домом (температура, движение, открытые окна),
а не управление устройством, поэтому доступ не фильтруется по устройствам.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from webui.routes import event_store


router = APIRouter(tags=["locations"])

#: Сколько часов истории отдаётся, если интервал не задан.
DEFAULT_HISTORY_HOURS = 24

#: Сколько записей истории отдаётся по умолчанию и сколько — максимум.
DEFAULT_HISTORY_LIMIT = 200
MAX_HISTORY_LIMIT = 2000


def _service(request: Request) -> Any:
    """Взять наблюдение за локациями у платформы.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Сервис наблюдения либо ``None``, если платформа не собрана.
    """
    container = getattr(request.app.state, "container", None)
    return getattr(container, "location_state", None)


def _unavailable() -> JSONResponse:
    """Ответ «наблюдение недоступно».

    Returns:
        JSON с описанием и кодом 503.
    """
    return JSONResponse(
        {"error": "Наблюдение за локациями не собрано: платформа недоступна"},
        status_code=503,
    )


def _parse_moment(value: str | None) -> float | None:
    """Разобрать момент времени из запроса.

    Принимается и ISO 8601 (``2026-10-13T09:00:00``), и секунды epoch: первый
    удобен человеку, второй — скриптам анализа.

    Args:
        value: Значение из запроса либо ``None``.

    Returns:
        Секунды epoch либо ``None``, если значение не задано.

    Raises:
        HTTPException: Если значение не разобрано (400).
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Не разобрано время {value!r}: ждём ISO 8601 или секунды epoch",
        ) from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


@router.get("/api/v1/locations", response_class=JSONResponse)
async def list_locations(request: Request) -> JSONResponse:
    """Перечислить локации: кто это и сколько у них датчиков.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON ``{"count": N, "locations": [...]}`` либо ошибка недоступности.
    """
    service = _service(request)
    if service is None:
        return _unavailable()
    locations = service.locations()
    return JSONResponse({"count": len(locations), "locations": locations})


@router.get("/api/v1/locations/{location_id}/state", response_class=JSONResponse)
async def get_location_state(location_id: str, request: Request) -> JSONResponse:
    """Отдать снимок локации: показания и производные.

    Args:
        location_id: Идентификатор локации.
        request: Входящий HTTP-запрос.

    Returns:
        JSON со снимком, 404 для неизвестной локации, 503 без платформы.
    """
    service = _service(request)
    if service is None:
        return _unavailable()
    snapshot = service.snapshot(location_id)
    if snapshot is None:
        return JSONResponse(
            {"error": f"Локация {location_id!r} не описана в манифесте"}, status_code=404
        )
    return JSONResponse(snapshot.model_dump(mode="json"))


@router.get("/api/v1/locations/{location_id}/history", response_class=JSONResponse)
async def get_location_history(
    location_id: str,
    request: Request,
    from_: str | None = Query(None, alias="from"),
    to_: str | None = Query(None, alias="to"),
    limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
) -> JSONResponse:
    """Отдать историю показателей локации за интервал (FR-006).

    Args:
        location_id: Идентификатор локации.
        request: Входящий HTTP-запрос.
        from_: Начало интервала (ISO 8601 или epoch); по умолчанию — минус сутки.
        to_: Конец интервала; по умолчанию — сейчас.
        limit: Сколько записей вернуть не больше.

    Returns:
        JSON с записями журнала: время, сущность, роль, было/стало.
    """
    service = _service(request)
    if service is None:
        return _unavailable()
    if location_id not in service.location_ids():
        return JSONResponse(
            {"error": f"Локация {location_id!r} не описана в манифесте"}, status_code=404
        )

    to_ts = _parse_moment(to_)
    if to_ts is None:
        to_ts = datetime.now(UTC).timestamp()
    from_ts = _parse_moment(from_)
    if from_ts is None:
        from_ts = to_ts - timedelta(hours=DEFAULT_HISTORY_HOURS).total_seconds()

    events = event_store.get_events_for_entities(
        service.sensor_entities(location_id), from_ts=from_ts, to_ts=to_ts, limit=limit
    )
    records = [
        {
            "at": datetime.fromtimestamp(event.timestamp or to_ts, tz=UTC).isoformat(),
            "entity_id": event.entity_id,
            "role": service.role_of(location_id, event.entity_id),
            "old_value": event.old_state,
            "value": event.new_state,
        }
        for event in events
    ]
    return JSONResponse(
        {
            "location_id": location_id,
            "from": datetime.fromtimestamp(from_ts, tz=UTC).isoformat(),
            "to": datetime.fromtimestamp(to_ts, tz=UTC).isoformat(),
            "count": len(records),
            "records": records,
        }
    )
