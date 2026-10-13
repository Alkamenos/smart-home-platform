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

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from webui.routes import event_store
from webui.services.manifest_runtime import apply_manifest_to_runtime, prime_location_state


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
    # Роли датчиков — из манифеста через наблюдение: интерфейсу они нужны, чтобы
    # показать и отредактировать привязку «роль → сущность» (спека 017, US5).
    for location in locations:
        sensors: dict[str, str] = {}
        for entity in service.sensor_entities(location["id"]):
            role = service.role_of(location["id"], entity)
            if role:
                sensors[role] = entity
        location["sensors"] = sensors
    return JSONResponse({"count": len(locations), "locations": locations})


#: Сущность Home Assistant: домен и объект.
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


class LocationSensorsUpdate(BaseModel):
    """Новая привязка ролей датчиков локации."""

    sensors: dict[str, str] = Field(
        default_factory=dict, description="Роль датчика → сущность Home Assistant"
    )


def _apply_sensors(manifest: Any, location_id: str, sensors: dict[str, str]) -> bool:
    """Записать привязки датчиков в модель манифеста.

    Комнаты манифеста — тоже локации, но их датчики лежат в ``rooms[].sensors``;
    особые зоны — в ``locations[].sensors``. Правка идёт туда, где локация
    объявлена, иначе изменение ушло бы в никуда.

    Args:
        manifest: Модель манифеста (веб-слоя).
        location_id: Идентификатор локации.
        sensors: Новая привязка ролей.

    Returns:
        True, если локация найдена и обновлена.
    """
    for room in getattr(manifest, "rooms", []):
        if room.id == location_id:
            room.sensors = dict(sensors)
            return True
    for location in getattr(manifest, "locations", []):
        if location.id == location_id:
            location.sensors = dict(sensors)
            return True
    return False


@router.put("/api/v1/locations/{location_id}", response_class=JSONResponse)
async def update_location_sensors(
    location_id: str, request: Request, body: LocationSensorsUpdate
) -> JSONResponse:
    """Задать роли датчиков локации (спека 017, US5, FR-026).

    Args:
        location_id: Идентификатор локации (комната или особая зона).
        request: Входящий HTTP-запрос.
        body: Новая привязка «роль → сущность».

    Returns:
        ``{"status": "saved", ...}`` при успехе; ``400`` при некорректной
        сущности; ``404`` для неизвестной локации; ``503`` без хранилища.
    """
    for role, entity in body.sensors.items():
        if not role.strip():
            raise HTTPException(status_code=400, detail="Роль датчика не может быть пустой")
        if not _ENTITY_RE.match(entity):
            raise HTTPException(
                status_code=400,
                detail=f"Сущность {entity!r} не похожа на сущность Home Assistant (домен.объект)",
            )

    store = getattr(request.app.state, "manifest_store", None)
    if store is None:
        return JSONResponse(
            {"error": "Хранилище манифеста недоступно: платформа не собрана"},
            status_code=503,
        )
    try:
        if store.current is None:
            store.load()
    except Exception as e:  # noqa: BLE001 — причина попадает в ответ
        return JSONResponse({"error": f"Манифест не прочитан: {e}"}, status_code=503)

    if not _apply_sensors(store.current, location_id, body.sensors):
        return JSONResponse(
            {"error": f"Локация {location_id!r} не описана в манифесте"}, status_code=404
        )

    store.save()

    container = getattr(request.app.state, "container", None)
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    warnings: list[str] = []
    try:
        apply_manifest_to_runtime(store, container, lifecycle_service)
        await prime_location_state(container)
    except Exception as exc:  # noqa: BLE001 — причина попадает в ответ
        warnings.append(f"Роли сохранены, но не применены в рантайме: {exc}")

    return JSONResponse({"status": "saved", "location_id": location_id, "warnings": warnings})


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
