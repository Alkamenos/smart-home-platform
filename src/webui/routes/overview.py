"""Агрегат для первого экрана «Дом» (спека 017, FR-007…FR-011, US1).

Один запрос вместо водопада из четырёх: локации со снимками, устройства с
состояниями автоматов и тревоги. Права применяются как в остальных чтениях:
устройства — по доступу пользователя, локации — агрегированное наблюдение за
домом (температура, движение, окна), не управление прибором.

Пустой дом — это ``200`` с пустыми списками, а не ошибка: «данных нет» и
«платформа недоступна» нельзя смешивать (FR-029).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from webui.models import build_all_fsm_state_views
from webui.routes import _resolve_accessible_device_ids, event_store
from webui.services.alerts import alerts_from_health, alerts_from_watchdog, build_alerts
from webui.services.decisions import decision_view
from webui.services.series import build_series


router = APIRouter(tags=["overview"])


def _container(request: Request) -> Any:
    """Взять контейнер платформы.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Контейнер либо ``None``.
    """
    return getattr(request.app.state, "container", None)


def _location_snapshots(container: Any) -> list[dict[str, Any]]:
    """Собрать снимки всех локаций.

    Args:
        container: Контейнер платформы.

    Returns:
        Список снимков (пустой, если наблюдение не собрано).
    """
    service = getattr(container, "location_state", None)
    if service is None:
        return []
    snapshots: list[dict[str, Any]] = []
    for location in service.locations():
        snapshot = service.snapshot(location["id"])
        if snapshot is not None:
            data = snapshot.model_dump(mode="json")
            data["series"] = build_series(event_store, service, location["id"])
            snapshots.append(data)
    return snapshots


def _manifest_entities(container: Any) -> set[str] | None:
    """Сущности приборов, объявленных в манифесте.

    Платформа хранит все импортированные сущности Home Assistant (их тысячи:
    обновления Supervisor, Zigbee2MQTT и прочее), но «дом» — это приборы из
    манифеста. Без этого фильтра первый экран тонул в шуме: 1495 устройств и
    сотни ложных тревог вместо 22 приборов дома.

    Args:
        container: Контейнер платформы.

    Returns:
        Множество сущностей либо ``None``, если манифест недоступен или пуст
        (тогда фильтрация не применяется).
    """
    manifest = getattr(container, "manifest", None)
    if manifest is None:
        return None
    entities = {
        device.id
        for room in getattr(manifest, "rooms", [])
        for device in getattr(room, "devices", [])
    }
    return entities or None


async def _devices(request: Request, allowed_entities: set[str] | None) -> list[dict[str, Any]]:
    """Собрать устройства, доступные пользователю.

    Args:
        request: Входящий HTTP-запрос.
        allowed_entities: Допустимые сущности (``None`` — без фильтрации, админ).

    Returns:
        Список представлений устройств.
    """
    service = getattr(request.app.state, "device_service", None)
    if service is None:
        return []
    if allowed_entities is None:
        devices = await service.get_all_devices()
    else:
        user_id = request.headers.get("X-User-ID") or str(
            getattr(request.app.state, "default_user_id", "") or ""
        )
        devices = await service.get_user_accessible_devices(user_id)

    # Дом — это приборы манифеста, а не все импортированные сущности HA.
    home_entities = _manifest_entities(_container(request))
    if home_entities is not None:
        devices = [
            device for device in devices if getattr(device, "ha_entity_id", None) in home_entities
        ]

    return [_device_view(device, _room_map(_container(request))) for device in devices]


def _house_name(container: Any) -> str:
    """Имя дома из манифеста — вместо служебного заголовка в шапке.

    Args:
        container: Контейнер платформы.

    Returns:
        Имя дома либо пустая строка.
    """
    instance = getattr(getattr(container, "manifest", None), "instance", None)
    return getattr(instance, "name", "") or ""


def _room_map(container: Any) -> dict[str, dict[str, str]]:
    """Карта «сущность прибора → комната» из манифеста.

    Грид «Автоматика» группируется по комнатам, а в хранилище устройств комнаты
    нет: она задаётся манифестом. Без этой карты группировать было бы не по чему.

    Args:
        container: Контейнер платформы.

    Returns:
        Сущность → ``{"id", "name"}`` комнаты.
    """
    manifest = getattr(container, "manifest", None)
    if manifest is None:
        return {}
    rooms: dict[str, dict[str, str]] = {}
    for room in getattr(manifest, "rooms", []):
        for device in getattr(room, "devices", []):
            rooms[device.id] = {"id": room.id, "name": room.name}
    return rooms


def _device_view(device: Any, rooms: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """Представить устройство для интерфейса.

    Args:
        device: Модель устройства платформы.
        rooms: Карта «сущность → комната» (для группировки).

    Returns:
        Словарь с полями, которые показывает интерфейс.
    """
    entity_id = getattr(device, "ha_entity_id", "") or ""
    name = getattr(device, "name", None) or entity_id
    room = (rooms or {}).get(entity_id) or {}
    return {
        "id": str(getattr(device, "id", "")),
        "name": name,
        "ha_entity_id": entity_id,
        "device_type": getattr(device, "device_type", "") or "",
        "status": getattr(device, "status", "") or "",
        "state": getattr(device, "state", {}) or {},
        "location": getattr(device, "ha_area_id", None),
        "room_id": room.get("id"),
        "room_name": room.get("name"),
    }


@router.get("/api/v1/overview", response_class=JSONResponse)
async def get_overview(request: Request) -> JSONResponse:
    """Отдать состояние дома для первого экрана.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON с локациями, устройствами, состояниями автоматов и тревогами,
        либо ``503``, если движок не собран.
    """
    container = _container(request)
    engine = getattr(container, "fsm", None)
    if container is None or engine is None:
        return JSONResponse(
            {"error": "Платформа недоступна: движок автоматов не собран"},
            status_code=503,
        )

    allowed_entities = await _resolve_accessible_device_ids(request)

    locations = _location_snapshots(container)
    devices = await _devices(request, allowed_entities)
    fsm_views = [view.model_dump() for view in build_all_fsm_state_views(engine, allowed_entities)]

    fsm_by_device: dict[str, list[dict[str, Any]]] = {}
    for view in fsm_views:
        fsm_by_device.setdefault(view.get("device_id") or "", []).append(view)
    for device in devices:
        views = fsm_by_device.get(device["ha_entity_id"], [])
        device["fsm"] = views
        device["decision"] = decision_view(
            engine, [view["fsm_id"] for view in views] + [device["ha_entity_id"]]
        )

    alerts = [alert.model_dump() for alert in build_alerts(locations, devices)]
    # Расхождение «автомат ↔ прибор» считает сторож: он читает прибор у Home
    # Assistant. Без этой строки «прибор горит, а решение — выключено» не видно
    # ни в журнале, ни в интерфейсе (концепция §7, п. 4).
    watchdog = getattr(container, "watchdog", None)
    alerts.extend(
        alert.model_dump()
        for alert in alerts_from_watchdog(getattr(watchdog, "last_snapshot", None))
    )
    # Обход дома (BACKLOG F6): проблемы за пределами приборов манифеста — датчики
    # улицы и грядок, батарейки, молчащие приборы.
    health = getattr(container, "house_health", None)
    alerts.extend(
        alert.model_dump() for alert in alerts_from_health(getattr(health, "last_report", None))
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "house_name": _house_name(container),
            "locations": locations,
            "devices": devices,
            "alerts": alerts,
        }
    )
