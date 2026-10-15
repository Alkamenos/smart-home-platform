"""Представления устройств и их автоматов для раздела устройств (BACKLOG B80).

Сборка ответов вынесена из `devices.py`: маршрут принимает запрос и отдаёт
готовое представление, а как оно собирается — отдельный вопрос.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import Request

from core.models.device import Device
from core.models.device_sync_event import DeviceSyncEvent
from core.models.manifest import BehaviorConfig
from webui.models import (
    FSMStateView,
    build_all_fsm_state_views,
    build_automation_info,
)
from webui.routes.devices.devices_models import (
    DeviceEventResponse,
    DeviceResponse,
    DeviceSelection,
)


logger = logging.getLogger(__name__)


def _build_device_fsm_views(request: Request, devices: list[Any]) -> dict[str, list[FSMStateView]]:
    """Собрать состояния автоматов устройств из движка (FR-019).

    Args:
        request: HTTP запрос (для доступа к контейнеру платформы).
        devices: Устройства, попавшие в ответ.

    Returns:
        Соответствие идентификатора устройства и его состояний автоматов.
    """
    container = getattr(request.app.state, "container", None)
    fsm_engine = getattr(container, "fsm", None)
    if fsm_engine is None:
        logger.debug("FSM engine unavailable: device automation info omitted")
        return {}

    entity_ids = {device.ha_entity_id for device in devices if device.ha_entity_id}
    views = build_all_fsm_state_views(fsm_engine, entity_ids)

    grouped: dict[str, list[FSMStateView]] = {}
    for view in views:
        grouped.setdefault(view.device_id, []).append(view)
    return grouped


def _build_device_behaviors_map(
    request: Request, devices: list[Any]
) -> dict[str, list[dict[str, Any]]]:
    """Собирает поведения устройств из манифеста по entity_id.

    Args:
        request: HTTP-запрос (из него берётся сервис жизненного цикла).
        devices: Устройства выборки.

    Returns:
        Словарь ``entity_id`` → поведения.
    """
    service = getattr(request.app.state, "lifecycle_service", None)
    if service is None:
        logger.debug("Lifecycle service unavailable: device behaviors omitted")
        return {}
    return {
        device.ha_entity_id: _device_behaviors(service, device.ha_entity_id) for device in devices
    }


def _device_behaviors(lifecycle: Any, ha_entity_id: str) -> list[dict[str, Any]]:
    """Возвращает поведения устройства из манифеста.

    Поведения хранятся в манифесте, а не в модели устройства, поэтому запрашиваются
    отдельно. Устройство, которого нет в манифесте, даёт пустой список, а не ошибку:
    ответ устройства не должен зависеть от целостности манифеста.

    Args:
        lifecycle: Сервис жизненного цикла либо None, если он недоступен.
        ha_entity_id: Идентификатор сущности Home Assistant.

    Returns:
        Список поведений в виде словарей.
    """
    manifest = getattr(lifecycle, "manifest", None)
    if manifest is None or not ha_entity_id:
        return []
    for room in getattr(manifest, "rooms", []):
        for config in room.devices:
            if config.id == ha_entity_id:
                return [behavior.model_dump() for behavior in config.behaviors]
    return []


def _to_device_response(
    device: Any,
    fsm_views: list[FSMStateView] | None = None,
    behaviors: list[dict[str, Any]] | None = None,
    decision: dict[str, Any] | None = None,
) -> DeviceResponse:
    """Собирает ответ API из модели устройства.

    Поля конфигурации (``display_name``, ``description``, ``location``,
    ``tags``) берутся из ``device.config`` — в модели устройства отдельных
    полей для них нет (spec 006, contracts/device-lifecycle-api.md).

    Устройство без автоматики получает явную отметку ``no_automation``, а не
    пустое значение состояния (spec 007, FR-019).

    Args:
        device: Модель устройства.
        fsm_views: Состояния автоматов устройства.
        behaviors: Поведения устройства из манифеста; при отсутствии — пустой список.
        decision: Последнее решение автоматики (спека 017, US3).

    Returns:
        Ответ API с устройством.
    """
    config = device.config or {}
    views = fsm_views or []
    return DeviceResponse(
        id=str(device.id),
        name=device.name,
        display_name=config.get("display_name"),
        device_type=device.device_type,
        status=device.status,
        state=device.state or {},
        source_id=str(device.source_id),
        ha_entity_id=device.ha_entity_id,
        ha_area_id=device.ha_area_id,
        description=config.get("description"),
        location=config.get("location"),
        tags=config.get("tags"),
        created_at=device.created_at.isoformat(),
        updated_at=device.updated_at.isoformat(),
        fsm=views,
        behaviors=behaviors or [],
        automation=build_automation_info([view.fsm_id for view in views]),
        decision=decision,
    )


def _to_event_response(event: DeviceSyncEvent) -> DeviceEventResponse:
    """Переводит запись истории в формат ответа эндпоинта events (research R5).

    Args:
        event: Запись истории операций

    Returns:
        Событие в формате DeviceEventResponse (event_type ← action).
    """
    payload = dict(event.data or {})
    payload["user_id"] = event.user_id
    payload["before"] = event.before
    payload["after"] = event.after
    return DeviceEventResponse(
        id=str(event.id),
        device_id=str(event.device_id),
        event_type=event.action,
        timestamp=event.timestamp.isoformat(),
        data=payload,
    )


def _current_user_id(request: Request) -> str:
    """Определяет инициатора операции по идентификации запроса.

    Args:
        request: HTTP запрос.

    Returns:
        Идентификатор пользователя или 'system', если идентификация не задана.
    """
    user_id = getattr(request.state, "user_id", None) or request.headers.get("X-User-ID")
    return user_id or "system"


def _find_room(manifest: Any, room_id: str) -> Any:
    """Ищет комнату в манифесте.

    Args:
        manifest: Модель манифеста.
        room_id: Идентификатор комнаты.

    Returns:
        Модель комнаты или None.
    """
    return next((room for room in manifest.rooms if room.id == room_id), None)


def _default_room_id(manifest: Any, device: Any = None) -> str:
    """Комната устройства: из его области в Home Assistant — и больше никак.

    Раньше здесь возвращалась **первая комната манифеста**, и устройства без
    явно выбранной комнаты молча складывались в неё: в боевом манифесте первой
    была ``kitchen``, и туда попали двадцать светильников, которых в описании
    дома быть не должно (Known Issue #88). Молчаливое размещение устройства в
    чужой комнате означает, что им управляет датчик не той комнаты, поэтому
    источник комнаты теперь один — область устройства в Home Assistant, а если
    её нет среди комнат манифеста, добавление отказывается.

    Args:
        manifest: Модель манифеста.
        device: Устройство, для которого ищется комната.

    Returns:
        Идентификатор комнаты устройства.

    Raises:
        ValueError: Если в манифесте нет комнат или область устройства среди них
            не значится.
    """
    if not manifest.rooms:
        msg = "В манифесте нет комнат: добавьте комнату перед добавлением устройств"
        raise ValueError(msg)

    area_id = getattr(device, "ha_area_id", None)
    if area_id:
        known = {room.id for room in manifest.rooms}
        if str(area_id) in known:
            return str(area_id)
        msg = (
            f"Устройство из области {area_id!r}: такой комнаты нет в манифесте. "
            "Укажите комнату вручную — молчаливый выбор другой означил бы, что "
            "устройством управляет датчик не той комнаты"
        )
        raise ValueError(msg)

    msg = (
        "Устройство без комнаты: выберите комнату или добавьте область "
        "в Home Assistant. Размещать наугад нельзя — устройство перестаёт "
        "управляться датчиками своей комнаты"
    )
    raise ValueError(msg)


def _build_device_from_selection(selection: DeviceSelection, source_id: UUID) -> Any:
    """Собирает модель устройства из выбора пользователя.

    Args:
        selection: Выбранное устройство.
        source_id: Источник устройства.

    Returns:
        Модель устройства.
    """
    domain = selection.device_entity_id.split(".")[0]
    return Device(
        ha_entity_id=selection.device_entity_id,
        source_id=source_id,
        name=selection.name or selection.device_entity_id,
        device_type=selection.device_type or domain,
        ha_area_id=selection.ha_area_id,
        state={},
        status="available",
    )


def _build_behaviors(selection: DeviceSelection) -> list[BehaviorConfig]:
    """Собирает список поведений устройства из выбора пользователя.

    Args:
        selection: Выбранное устройство.

    Returns:
        Список поведений (пустой, если шаблон не задан).
    """
    if selection.behaviors:
        return [
            BehaviorConfig(
                template=behavior.template, priority=behavior.priority, params=behavior.params
            )
            for behavior in selection.behaviors
        ]
    if selection.behavior_template:
        return [BehaviorConfig(template=selection.behavior_template, priority=10)]
    return []


def _room_of_device(lifecycle: Any, ha_entity_id: str) -> str | None:
    """Возвращает комнату устройства по его entity_id.

    Args:
        lifecycle: Сервис жизненного цикла.
        ha_entity_id: Идентификатор сущности Home Assistant.

    Returns:
        Идентификатор комнаты либо None, если устройства нет в манифесте.
    """
    for room in getattr(lifecycle.manifest, "rooms", []):
        for config in room.devices:
            if config.id == ha_entity_id:
                return room.id
    return None
