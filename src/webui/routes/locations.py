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
from pydantic import BaseModel, Field, ValidationError

from core.models.manifest import iter_role_entities
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


@router.get("/api/v1/locations", response_class=JSONResponse, response_model=dict[str, Any])
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
        sensors: dict[str, list[str]] = {}
        for entity in service.sensor_entities(location["id"]):
            role = service.role_of(location["id"], entity)
            if role:
                sensors.setdefault(role, []).append(entity)
        location["sensors"] = sensors
    # Место в дереве и его приборы — из манифеста: интерфейсу нужны родитель и
    # состав, чтобы показать дерево и переносить приборы (B93).
    store = _require_store(request)
    manifest = getattr(store, "current", None)
    for location in locations:
        place = None
        if manifest is not None:
            place = next(
                (
                    item
                    for item in [*manifest.rooms, *manifest.locations]
                    if item.id == location["id"]
                ),
                None,
            )
        location["parent"] = getattr(place, "parent", None) if place is not None else None
        location["devices"] = (
            [
                {
                    "id": device.id,
                    "name": device.name or device.id,
                    "type": device.type,
                    "behaviors": len(device.behaviors),
                }
                for device in (getattr(place, "devices", []) or [])
            ]
            if place is not None
            else []
        )
    return JSONResponse({"count": len(locations), "locations": locations})


#: Сущность Home Assistant: домен и объект.
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")

#: Идентификатор места: латиница, цифры и подчёркивание (идёт в пути и в правилах).
_PLACE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class LocationUpdate(BaseModel):
    """Правка места: имя, вид, родитель и роли датчиков.

    Все поля необязательные: интерфейс меняет то, что человек тронул, а не
    перезаписывает место целиком. Какое поле пришло — видно по
    ``model_fields_set``, поэтому ``parent: null`` означает «сделать местом
    верхнего уровня», а отсутствие поля — «не трогать».
    """

    name: str | None = Field(None, description="Человекочитаемое имя места")
    kind: str | None = Field(None, description="Вид места: room, outdoor, garden, …")
    parent: str | None = Field(None, description="Место верхнего уровня (id) либо null")
    sensors: dict[str, str | list[str]] | None = Field(
        None, description="Роль датчика → сущность или список сущностей"
    )


class PlaceCreate(BaseModel):
    """Новое место: комната (``kind: room``) или локация."""

    id: str = Field(..., description="Идентификатор места (латиница, цифры, подчёркивание)")
    name: str = Field(..., description="Человекочитаемое имя")
    kind: str = Field("other", description="Вид места; ``room`` создаёт комнату")
    parent: str | None = Field(None, description="Место верхнего уровня (id)")


class DeviceMove(BaseModel):
    """Перенос прибора в другое место."""

    device_id: str = Field(..., description="Сущность Home Assistant, описанная в манифесте")


def _require_store(request: Request) -> Any | None:
    """Взять хранилище манифеста.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Хранилище либо ``None``, если платформа не собрана или манифест не читается.
    """
    store = getattr(request.app.state, "manifest_store", None)
    if store is None:
        return None
    try:
        if store.current is None:
            store.load()
    except Exception:  # noqa: BLE001 — причина попадёт в ответ вызывающего
        return None
    return store


def _places_data(manifest: Any) -> list[dict[str, Any]]:
    """Разделы мест как словари: комнаты и локации.

    Args:
        manifest: Модель манифеста.

    Returns:
        Список словарей мест (из ``model_dump``), чтобы правка шла по копии, а не
        по живому объекту: ошибку проверки нельзя оставлять в модели.
    """
    return [*manifest["rooms"], *manifest["locations"]]


def _find_place_data(manifest: dict[str, Any], place_id: str) -> dict[str, Any] | None:
    """Найти место в словаре манифеста.

    Args:
        manifest: Манифест как словарь.
        place_id: Идентификатор места.

    Returns:
        Словарь места либо ``None``.
    """
    return next((place for place in _places_data(manifest) if place["id"] == place_id), None)


def _find_device(
    manifest: dict[str, Any], device_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Найти прибор и место, в котором он описан.

    Args:
        manifest: Манифест как словарь.
        device_id: Сущность прибора.

    Returns:
        Пара «место, прибор» либо ``(None, None)``.
    """
    for place in _places_data(manifest):
        for device in place.get("devices") or []:
            if device.get("id") == device_id:
                return place, device
    return None, None


def _validated(store: Any, data: dict[str, Any]) -> tuple[Any | None, JSONResponse | None]:
    """Проверить изменённый манифест моделью.

    Правка идёт по словарю, поэтому проверки модели (в том числе инварианты
    дерева мест) нужно запустить явно: иначе неверный родитель или цикл уехали бы
    в файл мимо проверки.

    Args:
        store: Хранилище манифеста.
        data: Изменённый манифест как словарь.

    Returns:
        Пару «модель, ошибка»: ровно одно из двух не ``None``.
    """
    try:
        return store.model_type(**data), None
    except ValidationError as exc:
        fields = [
            {
                "loc": ".".join(str(part) for part in error.get("loc", ())),
                "message": error.get("msg", "некорректное значение"),
            }
            for error in exc.errors()
        ]
        return None, JSONResponse(
            {"error": "Манифест не принят проверкой", "fields": fields},
            status_code=400,
        )


async def _apply_and_report(request: Request, store: Any) -> list[str]:
    """Применить правку к работающей платформе и собрать предупреждения.

    Args:
        request: Входящий HTTP-запрос.
        store: Хранилище манифеста.

    Returns:
        Список предупреждений: правка сохранена, но не применена.
    """
    container = getattr(request.app.state, "container", None)
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    warnings: list[str] = []
    try:
        apply_manifest_to_runtime(store, container, lifecycle_service)
        await prime_location_state(container)
    except Exception as exc:  # noqa: BLE001 — причина попадает в ответ
        warnings.append(f"Сохранено, но не применено в рантайме: {exc}")
    return warnings


def _validate_sensors(sensors: dict[str, Any]) -> None:
    """Проверить привязку ролей датчиков.

    Args:
        sensors: Роль → сущность или список сущностей.

    Raises:
        HTTPException: Если роль пустая или сущность не похожа на сущность дома.
    """
    for role, entity in iter_role_entities(sensors):
        if not role.strip():
            raise HTTPException(status_code=400, detail="Роль датчика не может быть пустой")
        if not _ENTITY_RE.match(entity):
            raise HTTPException(
                status_code=400,
                detail=f"Сущность {entity!r} не похожа на сущность Home Assistant (домен.объект)",
            )


@router.put(
    "/api/v1/locations/{location_id}", response_class=JSONResponse, response_model=dict[str, Any]
)
async def update_location(location_id: str, request: Request, body: LocationUpdate) -> JSONResponse:
    """Изменить место: имя, вид, родителя и роли датчиков (B93).

    Правка идёт через манифест, а не через YAML руками: интерфейс и файл не
    расходятся, а инварианты дерева мест проверяются моделью.

    Args:
        location_id: Идентификатор места (комната или локация).
        request: Входящий HTTP-запрос.
        body: Что меняем; поля, которых нет в теле, не трогаются.

    Returns:
        ``{"status": "saved", ...}`` при успехе; ``400`` при некорректных
        значениях, ``404`` для неизвестного места, ``503`` без хранилища.
    """
    store = _require_store(request)
    if store is None:
        return JSONResponse(
            {"error": "Хранилище манифеста недоступно: платформа не собрана"},
            status_code=503,
        )

    data = store.current.model_dump()
    place = _find_place_data(data, location_id)
    if place is None:
        return JSONResponse(
            {"error": f"Локация {location_id!r} не описана в манифесте"}, status_code=404
        )

    provided = body.model_fields_set
    if "sensors" in provided:
        sensors = dict(body.sensors or {})
        _validate_sensors(sensors)
        place["sensors"] = sensors
    if "name" in provided:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Имя места не может быть пустым")
        place["name"] = name
    if "kind" in provided:
        kind = (body.kind or "").strip()
        if not kind:
            raise HTTPException(status_code=400, detail="Вид места не может быть пустым")
        place["kind"] = kind
    if "parent" in provided:
        parent = (body.parent or "").strip()
        place["parent"] = parent or None

    model, error = _validated(store, data)
    if error is not None:
        return error
    store.current = model
    store.save()

    warnings = await _apply_and_report(request, store)
    return JSONResponse(
        {
            "status": "saved",
            "location_id": location_id,
            "changed": sorted(provided),
            "warnings": warnings,
        }
    )


@router.post(
    "/api/v1/locations", status_code=201, response_class=JSONResponse, response_model=dict[str, Any]
)
async def create_location(request: Request, body: PlaceCreate) -> JSONResponse:
    """Завести новое место — комнату или локацию (B93).

    Args:
        request: Входящий HTTP-запрос.
        body: Идентификатор, имя, вид и родитель.

    Returns:
        ``{"status": "created", ...}``; ``400`` при некорректных значениях,
        ``409`` если место с таким идентификатором уже есть.
    """
    store = _require_store(request)
    if store is None:
        return JSONResponse(
            {"error": "Хранилище манифеста недоступно: платформа не собрана"},
            status_code=503,
        )

    place_id = body.id.strip()
    if not _PLACE_ID_RE.match(place_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Идентификатор {place_id!r} не годится: латиница, цифры и подчёркивание, "
                f"начинается с буквы"
            ),
        )
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Имя места не может быть пустым")

    data = store.current.model_dump()
    if _find_place_data(data, place_id) is not None:
        return JSONResponse(
            {"error": f"Место {place_id!r} уже описано в манифесте"}, status_code=409
        )

    kind = body.kind.strip() or "other"
    entry: dict[str, Any] = {
        "id": place_id,
        "name": name,
        "kind": kind,
        "parent": (body.parent or "").strip() or None,
        "sensors": {},
        "devices": [],
    }
    section = "rooms" if kind == "room" else "locations"
    data[section].append(entry)

    model, error = _validated(store, data)
    if error is not None:
        return error
    store.current = model
    store.save()

    warnings = await _apply_and_report(request, store)
    return JSONResponse(
        {
            "status": "created",
            "location_id": place_id,
            "section": section,
            "warnings": warnings,
        },
        status_code=201,
    )


@router.delete(
    "/api/v1/locations/{location_id}", response_class=JSONResponse, response_model=dict[str, Any]
)
async def delete_location(location_id: str, request: Request) -> JSONResponse:
    """Удалить пустое место.

    Удаление разрешено только для места без приборов, датчиков и детей: иначе
    часть дома молча выпала бы из автоматики. Сначала перенесите приборы и
    датчики, потом удаляйте.

    Args:
        location_id: Идентификатор места.
        request: Входящий HTTP-запрос.

    Returns:
        ``{"status": "deleted"}``; ``409`` если место не пустое.
    """
    store = _require_store(request)
    if store is None:
        return JSONResponse(
            {"error": "Хранилище манифеста недоступно: платформа не собрана"},
            status_code=503,
        )

    data = store.current.model_dump()
    place = _find_place_data(data, location_id)
    if place is None:
        return JSONResponse(
            {"error": f"Локация {location_id!r} не описана в манифесте"}, status_code=404
        )

    children = [item["name"] for item in _places_data(data) if item.get("parent") == location_id]
    devices = [device.get("id") for device in place.get("devices") or []]
    sensors = list((place.get("sensors") or {}).keys())
    if children or devices or sensors:
        return JSONResponse(
            {
                "error": (
                    f"Место {location_id!r} не пустое: сначала перенесите приборы и датчики "
                    f"и разберите вложенные места"
                ),
                "children": children,
                "devices": devices,
                "sensor_roles": sensors,
            },
            status_code=409,
        )

    section = "rooms" if location_id in {item["id"] for item in data["rooms"]} else "locations"
    data[section] = [item for item in data[section] if item["id"] != location_id]

    model, error = _validated(store, data)
    if error is not None:
        return error
    store.current = model
    store.save(allow_removal=True)

    warnings = await _apply_and_report(request, store)
    return JSONResponse({"status": "deleted", "location_id": location_id, "warnings": warnings})


@router.post(
    "/api/v1/locations/{location_id}/devices",
    response_class=JSONResponse,
    response_model=dict[str, Any],
)
async def move_device(location_id: str, request: Request, body: DeviceMove) -> JSONResponse:
    """Перенести прибор в это место (B93).

    Прибор описывается в манифесте один раз, поэтому перенос — это удаление из
    прежнего места и добавление в новое. Автоматика прибора не меняется: правила
    поведения остаются с ним, а место нужно для правил «комнат без окон» и для
    панели дома.

    Args:
        location_id: Куда переносим.
        request: Входящий HTTP-запрос.
        body: Какой прибор переносим.

    Returns:
        ``{"status": "saved", "moved": true, "from": ...}``; ``404`` если прибор
        или место не найдены, ``503`` без хранилища.
    """
    store = _require_store(request)
    if store is None:
        return JSONResponse(
            {"error": "Хранилище манифеста недоступно: платформа не собрана"},
            status_code=503,
        )

    data = store.current.model_dump()
    target = _find_place_data(data, location_id)
    if target is None:
        return JSONResponse(
            {"error": f"Локация {location_id!r} не описана в манифесте"}, status_code=404
        )

    source, device = _find_device(data, body.device_id)
    if source is None or device is None:
        return JSONResponse(
            {"error": f"Прибор {body.device_id!r} не описан ни в одном месте манифеста"},
            status_code=404,
        )
    if source["id"] == location_id:
        return JSONResponse(
            {
                "status": "unchanged",
                "moved": False,
                "from": source["id"],
                "to": location_id,
            }
        )

    source["devices"] = [
        item for item in source.get("devices") or [] if item.get("id") != body.device_id
    ]
    target.setdefault("devices", []).append(device)

    model, error = _validated(store, data)
    if error is not None:
        return error
    store.current = model
    store.save(allow_removal=True)

    warnings = await _apply_and_report(request, store)
    return JSONResponse(
        {
            "status": "saved",
            "moved": True,
            "device_id": body.device_id,
            "from": source["id"],
            "to": location_id,
            "warnings": warnings,
        }
    )


@router.get(
    "/api/v1/locations/{location_id}/state",
    response_class=JSONResponse,
    response_model=dict[str, Any],
)
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


@router.get(
    "/api/v1/locations/{location_id}/history",
    response_class=JSONResponse,
    response_model=dict[str, Any],
)
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
