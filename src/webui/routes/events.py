"""Журнал интерфейса: живая лента событий и переходов (спека 017, US4).

Один запрос отдаёт и изменения состояний датчиков, и переходы автоматов, с
фильтрами по сущности/локации/трассировке и курсором для «подгрузки старше».
Уровня важности в схеме нет, поэтому фильтр по уровню не поддерживается —
показывать выдуманный уровень было бы хуже, чем его отсутствие.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from webui.routes import event_store


router = APIRouter(tags=["events"])

#: Сколько записей отдаётся по умолчанию и максимум.
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _parse_moment(value: str | None) -> float | None:
    """Разобрать момент времени: ISO 8601 или секунды epoch.

    Args:
        value: Значение из запроса либо ``None``.

    Returns:
        Секунды epoch либо ``None``, если значение не задано.

    Raises:
        HTTPException: 400, если значение не разобрано.
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
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Не разобрано время {value!r}: ждём ISO 8601 или секунды epoch",
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _record(row: dict[str, Any]) -> dict[str, Any]:
    """Представить строку журнала для интерфейса.

    Args:
        row: Строка из ``EventStore.query_journal``.

    Returns:
        Запись с человекочитаемым текстом и временем в ISO.
    """
    timestamp = row.get("timestamp") or 0.0
    at = datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    kind = row.get("kind")
    entity_id = row.get("entity_id") or ""
    if kind == "transition":
        rejected = row.get("success") in (0, False)
        message = (
            f"{entity_id}: {row.get('from_state')} → {row.get('to_state')}"
            f" ({row.get('trigger_name')})"
        )
        if rejected and row.get("reason"):
            message = f"{message} — отклонён: {row['reason']}"
        value = row.get("to_state")
        old_value = row.get("from_state")
        title = "Переход отклонён" if rejected else "Переход автомата"
    else:
        message = f"{entity_id}: {row.get('old_state')} → {row.get('new_state')}"
        value = row.get("new_state")
        old_value = row.get("old_state")
        title = row.get("detail") or "Событие"

    return {
        "at": at,
        "at_ts": timestamp,
        "kind": kind,
        "entity_id": entity_id,
        "title": title,
        "message": message,
        "trace_id": row.get("trace_id"),
        "old_value": old_value,
        "value": value,
    }


@router.get("/api/v1/events", response_class=JSONResponse)
async def get_events(
    request: Request,
    entity: str | None = Query(None, description="Сущность (датчик или автомат)"),
    device: str | None = Query(None, description="Синоним сущности прибора"),
    location: str | None = Query(None, description="Локация: все её датчики"),
    trace: str | None = Query(None, description="Трассировка"),
    from_: str | None = Query(None, alias="from"),
    to_: str | None = Query(None, alias="to"),
    before: str | None = Query(None, description="Курсор: записи старше этого момента"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> JSONResponse:
    """Отдать ленту журнала с фильтрами.

    Args:
        request: Входящий HTTP-запрос.
        entity: Фильтр по сущности.
        device: Синоним ``entity`` для страницы прибора.
        location: Локация — журнал по всем её датчикам.
        trace: Фильтр по трассировке.
        from_: Начало интервала.
        to_: Конец интервала.
        before: Курсор для подгрузки старше.
        limit: Сколько записей вернуть не больше.

    Returns:
        JSON ``{"records": [...], "next_cursor": <epoch|null>}``. Неизвестная
        локация — 404, непонятное время — 400, недоступное наблюдение — 503.
    """
    entity_ids: list[str] = []
    target = entity or device
    if target:
        entity_ids.append(target)

    if location:
        service = getattr(getattr(request.app.state, "container", None), "location_state", None)
        if service is None:
            return JSONResponse(
                {"error": "Наблюдение за локациями не собрано: платформа недоступна"},
                status_code=503,
            )
        if location not in service.location_ids():
            return JSONResponse(
                {"error": f"Локация {location!r} не описана в манифесте"}, status_code=404
            )
        entity_ids.extend(service.sensor_entities(location))

    rows = event_store.query_journal(
        entity_ids=entity_ids if entity_ids else None,
        trace_id=trace,
        from_ts=_parse_moment(from_),
        to_ts=_parse_moment(to_),
        before_ts=_parse_moment(before),
        limit=limit,
    )
    records = [_record(row) for row in rows]
    next_cursor = records[-1]["at_ts"] if len(records) == limit else None

    return JSONResponse(
        {
            "count": len(records),
            "records": records,
            "next_cursor": next_cursor,
        }
    )
