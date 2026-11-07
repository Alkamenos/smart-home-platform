"""Device command routes (spec 018, T059)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from webui.routes.devices.deps import get_device_service, record_sync_event
from webui.routes.devices.devices_common import (
    _ROLE_CONTROLLER,
    _ROLE_VIEWER,
    _require_access_or_403,
)
from webui.routes.devices.devices_models import CommandRequest, CommandResponse


logger = logging.getLogger(__name__)
router = APIRouter()

_MANUAL_FSM_EVENTS: dict[str, str] = {
    "turn_on": "manual_switch_on",
    "turn_off": "manual_switch_off",
}


@router.post("/{device_id}/command", status_code=status.HTTP_200_OK, response_model=CommandResponse)
async def execute_device_command(
    device_id: UUID,
    http_request: Request,
    request: CommandRequest,
) -> CommandResponse:
    """T054: Отправляет команду устройству.

    Единый endpoint команды (стаб send_device_command объединён сюда):
    принимает форматы T054 (``name`` + обязательные ``parameters``),
    name-алиас (``command_name``, параметры необязательны) и сервисный
    формат (``service``/``data``).

    Args:
        device_id: ID устройства
        http_request: HTTP запрос (идентификация из middleware)
        request: Команда для выполнения

    Returns:
        Статус выполнения команды

    Raises:
        HTTPException: 403 если нет роли controller; 404 если устройство не найдено
            или 400 при ошибке валидации
    """
    device_service = get_device_service(http_request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(http_request, device_id, _ROLE_CONTROLLER)

    from uuid import uuid4

    command_id = str(uuid4())
    effective_name = request.command_name or request.name or request.service or "unknown"
    # Пустой словарь — это осмысленное «без параметров», а не повод брать `data`.
    # Прежняя проверка `if request.parameters else request.data` подставляла None,
    # и распаковка `**None` роняла вызов с TypeError.
    parameters = request.parameters or request.data or {}

    # Имя сервиса может прийти с доменом («light.turn_on»). Домен берётся из типа
    # устройства, поэтому из имени он убирается: иначе HA получил бы
    # сервис «light.turn_on» в домене light и ответил бы ошибкой.
    service = effective_name.split(".", 1)[1] if "." in effective_name else effective_name

    logger.info(f"Выполняю команду {service} на устройстве {device_id}")

    # Сначала автомат: он и переключит состояние, и вызовет Home Assistant своим
    # действием. Прямой вызов HA оставил бы автомат в неведении, и следующее
    # событие датчика отменило бы ручное действие пользователя.
    result: dict[str, Any] | None = None
    fsm_event = _MANUAL_FSM_EVENTS.get(service)
    handled_by_fsm = False
    if fsm_event is not None:
        container = getattr(http_request.app.state, "container", None)
        if container is not None:
            for fsm_id in container.fsm.get_entities_by_device(device.ha_entity_id):
                context = {
                    "entity_id": device.ha_entity_id,
                    "target_device_id": device.ha_entity_id,
                    "source": "manual_command",
                    **parameters,
                }
                if await container.fsm.trigger(fsm_id, fsm_event, context):
                    handled_by_fsm = True
                    break
        if handled_by_fsm:
            logger.info(f"Команда {service} выполнена через автомат: {fsm_event}")

    if not handled_by_fsm:
        try:
            result = await device_service._call_ha_service(device, service, parameters)
        except Exception as e:
            logger.error(f"Команда {service} для {device.ha_entity_id} не выполнена: {e}")
            await record_sync_event(
                http_request,
                device_id,
                "command_failed",
                before=None,
                after=None,
                data={"command": service, "error": str(e)},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Команда {service} не выполнена: {e}",
            ) from e

    await record_sync_event(
        http_request,
        device_id,
        "command_executed",
        before=None,
        after=None,
        data={
            "command": service,
            "parameters": parameters,
            "via_fsm": handled_by_fsm,
            "fsm_event": fsm_event if handled_by_fsm else None,
        },
    )

    return CommandResponse(
        id=command_id,
        device_id=str(device_id),
        command_name=effective_name,
        status="success",
        created_at=datetime.utcnow().isoformat(),
        completed_at=datetime.utcnow().isoformat(),
        result=result,
        automation_synced=handled_by_fsm,
    )


# ============ T056: GET /api/v1/devices/{id}/command/{command_id} ============


@router.get(
    "/{device_id}/command/{command_id}",
    status_code=status.HTTP_200_OK,
    response_model=dict[str, Any] | None,
)
async def get_command_status(
    device_id: UUID,
    command_id: UUID,
    request: Request,
) -> CommandResponse:
    """T056: Получает статус выполненной команды.

    Args:
        device_id: ID устройства
        command_id: ID команды
        request: HTTP запрос (идентификация из middleware)

    Returns:
        Информация о статусе команды

    Raises:
        HTTPException: 403 если нет роли viewer; 404 если устройство или команда не найдены
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_VIEWER)

    try:
        # TODO: Получить статус команды из DeviceService._commands
        # Здесь заглушка
        logger.info(f"Получаю статус команды {command_id}")

        return CommandResponse(
            id=str(command_id),
            device_id=str(device_id),
            command_name="unknown",
            status="unknown",
            created_at=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        logger.error(f"Ошибка при получении статуса команды: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении статуса команды",
        ) from e


# ============ T057: GET /api/v1/devices/{id}/events ============
