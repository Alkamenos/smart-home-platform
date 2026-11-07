"""
API маршруты для управления устройствами.

Включает операции получения, обновления конфигурации и отправки команд устройствам.
Реализует фильтрацию по доступу пользователя.
"""

import contextlib
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from core.models.manifest import BehaviorConfig
from webui.routes.devices.access_control import require_admin
from webui.routes.devices.deps import (
    get_device_service,
    get_lifecycle_service,
    record_sync_event,
)
from webui.routes.devices.devices_commands import router as commands_router
from webui.routes.devices.devices_common import (
    _ROLE_ADMIN,
    _ROLE_CONTROLLER,
    _require_access_or_403,
)
from webui.routes.devices.devices_delete import router as delete_router
from webui.routes.devices.devices_models import (
    ApplyDevicesRequest as ApplyDevicesRequest,
    ApplyDevicesResponse as ApplyDevicesResponse,
    BehaviorSelection as BehaviorSelection,
    BehaviorsUpdateRequest as BehaviorsUpdateRequest,
    BehaviorsUpdateResponse as BehaviorsUpdateResponse,
    CommandRequest as CommandRequest,
    CommandResponse as CommandResponse,
    DeviceEventResponse as DeviceEventResponse,
    DeviceResponse as DeviceResponse,
    DeviceSelection as DeviceSelection,
    FailedDevice as FailedDevice,
    UpdateDeviceConfigRequest as UpdateDeviceConfigRequest,
)
from webui.routes.devices.devices_read import get_devices, router as read_router
from webui.routes.devices.devices_views import (
    _build_behaviors as _build_behaviors,
    _build_device_behaviors_map as _build_device_behaviors_map,
    _build_device_from_selection as _build_device_from_selection,
    _build_device_fsm_views as _build_device_fsm_views,
    _current_user_id as _current_user_id,
    _default_room_id as _default_room_id,
    _device_behaviors as _device_behaviors,
    _find_room as _find_room,
    _room_of_device as _room_of_device,
    _to_device_response as _to_device_response,
    _to_event_response as _to_event_response,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])
router.include_router(read_router)
router.include_router(delete_router)
router.add_api_route("", get_devices, methods=["GET"], status_code=status.HTTP_200_OK)
router.include_router(commands_router)

# Требуемые роли на операции (contracts §1, data-model иерархия)
# Literal-типизация: DeviceService принимает роли как Literal["viewer", ...],
# а значения ниже — единственные, которые вообще передаются в проверку доступа.
# ============ T033-T057: Управление устройствами (полная реализация) ============


@router.put("/{device_id}/config", status_code=status.HTTP_200_OK)
async def update_device_config(
    device_id: UUID, http_request: Request, request: UpdateDeviceConfigRequest
) -> DeviceResponse:
    """T032/T038: Обновляет конфигурацию устройства.

    Обновляет параметры конфигурации устройства:
    - display_name (1-255 символов, уникально в пределах источника)
    - description (макс 1000 символов)
    - location (макс 255 символов)
    - tags (макс 10 тегов по 50 символов каждый)

    Args:
        device_id: ID устройства
        http_request: HTTP запрос (идентификация из middleware)
        request: Данные конфигурации

    Returns:
        Обновленное устройство с конфигурацией

    Raises:
        HTTPException: 403 если нет роли admin; 404 если устройство не найдено
        HTTPException: 422 если валидация не пройдена
    """
    device_service = get_device_service(http_request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(http_request, device_id, _ROLE_ADMIN)

    try:
        # Валидируем теги
        if request.tags is not None:
            if len(request.tags) > 10:
                raise ValueError("Не может быть более 10 тегов")
            for tag in request.tags:
                if len(tag) > 50:
                    raise ValueError(f"Тег '{tag}' слишком длинный (макс 50 символов)")

        # Инициализируем конфигурацию, если её ещё нет (модель устройства,
        # а не словарь — устройство приходит из единого источника, spec 006)
        config = dict(device.config or {})
        if not config:
            config = {"id": str(UUID(int=1)), "device_id": str(device_id)}

        # Снимок изменяемых полей ДО обновления (ТР-010, spec 005)
        updated_fields = [
            name
            for name in ("display_name", "description", "location", "tags")
            if getattr(request, name) is not None
        ]
        before_snapshot = {name: config.get(name) for name in updated_fields}

        # Обновляем поля если они указаны
        if request.display_name is not None:
            config["display_name"] = request.display_name

        if request.description is not None:
            config["description"] = request.description

        if request.location is not None:
            config["location"] = request.location

        if request.tags is not None:
            config["tags"] = request.tags

        config["updated_at"] = datetime.utcnow().isoformat()
        device.config = config
        await device_service.add_device(device)

        logger.info(f"Обновлена конфигурация устройства {device_id}")

        after_snapshot = {name: config.get(name) for name in updated_fields}
        await record_sync_event(
            http_request,
            device_id,
            "config_changed",
            before=before_snapshot,
            after=after_snapshot,
        )

        return _to_device_response(
            device,
            behaviors=_device_behaviors(get_lifecycle_service(http_request), device.ha_entity_id),
        )

    except ValueError as e:
        logger.error(f"Ошибка валидации при обновлении конфигурации устройства: {e}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Ошибка при обновлении конфигурации устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при обновлении конфигурации",
        ) from e


@router.post("/apply", status_code=status.HTTP_201_CREATED)
async def apply_devices(
    request: Request,
    body: ApplyDevicesRequest,
    is_admin: bool = Depends(require_admin),
) -> ApplyDevicesResponse:
    """Применяет выбранные устройства из Home Assistant.

    Единственная точка применения набора устройств (FR-005). Обработчик
    идемпотентен по ``device_entity_id``: повторное применение тех же данных
    обновляет устройство, а не создаёт дубль (FR-008). При ``dry_run``
    ни манифест, ни хранилище не меняются.

    Args:
        request: HTTP запрос (для получения сервисов и идентификации).
        body: Запрос с выбранными устройствами.

    Returns:
        Результат применения с перечнем добавленных и неудачных устройств.

    Raises:
        HTTPException: 401 без идентификации, 403 без роли администратора,
            404 если источник не найден, 500 при внутренней ошибке.
    """
    if not body.selections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Список устройств не может быть пустым",
        )

    lifecycle = get_lifecycle_service(request)
    user_id = _current_user_id(request)

    if body.dry_run:
        room_ids = {selection.target_room for selection in body.selections if selection.target_room}
        missing = [room for room in room_ids if _find_room(lifecycle.manifest, room) is None]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Комнаты не найдены в манифесте: {', '.join(sorted(missing))}",
            )
        logger.info(
            f"Тестовый запуск применения: {len(body.selections)} устройств, "
            f"комнаты: {', '.join(sorted(room_ids)) or 'по умолчанию'}"
        )
        return ApplyDevicesResponse(
            success=True,
            devices_count=0,
            dry_run=True,
            would_add=len(body.selections),
        )

    applied: list[DeviceResponse] = []
    failed: list[FailedDevice] = []
    added = 0
    updated = 0

    # Пачка применяется одной записью манифеста: раньше файл переписывался на
    # каждое устройство, и резервная копия успевала исчезнуть до того, как
    # владелец заметил бы потерю (Known Issue #88).
    store = getattr(lifecycle, "manifest_store", None)
    batch = store.batch() if store is not None else contextlib.nullcontext()
    with batch:
        for selection in body.selections:
            try:
                device = _build_device_from_selection(selection, body.source_id)
                behaviors = _build_behaviors(selection)
                # Комната: выбранная владельцем либо область устройства в HA.
                # Молчаливый выбор «первой комнаты» и есть причина, по которой
                # двадцать чужих светильников оказались в кухне (Known Issue #88).
                room_id = selection.target_room or _default_room_id(lifecycle.manifest, device)

                device, saved = await lifecycle.add_device(
                    device, room_id=room_id, behaviors=behaviors, user_id=user_id
                )
                if saved:
                    added += 1
                else:
                    updated += 1
                applied.append(
                    _to_device_response(
                        device,
                        behaviors=_device_behaviors(
                            get_lifecycle_service(request), device.ha_entity_id
                        ),
                    )
                )
            except Exception as e:
                reason = str(e)
                logger.error(f"Не удалось применить {selection.device_entity_id}: {reason}")
                failed.append(FailedDevice(ha_entity_id=selection.device_entity_id, reason=reason))

    logger.info(
        f"Применение завершено: добавлено {added}, обновлено {updated}, ошибок {len(failed)}"
    )
    return ApplyDevicesResponse(
        success=not failed,
        devices_count=len(applied),
        devices=applied,
        devices_added=added,
        devices_updated=updated,
        failed=len(failed),
        failed_devices=failed,
        errors=[f"{item.ha_entity_id}: {item.reason}" for item in failed] or None,
    )


# ============ Пункт 4: правка поведений устройства ============


@router.put("/{device_id}/behaviors", response_class=JSONResponse)  # type: ignore[untyped-decorator]
async def update_device_behaviors(
    device_id: UUID,
    body: BehaviorsUpdateRequest,
    http_request: Request,
) -> JSONResponse:
    """Заменяет поведения устройства, проверяя параметры по контракту.

    Проверка идёт до записи и до обращения к сервису жизненного цикла: устройство,
    чьи параметры отвергнуты, не должно менять состояние и не должно попадать в
    журнал аудита как обновлённое.

    Args:
        device_id: Идентификатор устройства.
        body: Новый список поведений.
        http_request: HTTP-запрос (идентификация из middleware).

    Returns:
        Ответ с сохранёнными поведениями и перечнем инертных параметров.

    Raises:
        HTTPException: 404 если устройство не найдено, 403 без роли контроллера,
            400 при нарушении одного из пяти слоёв проверки.
    """
    from core.behavior_params import ParamError, load_contract, validate_behavior

    device_service = get_device_service(http_request)
    await _require_access_or_403(http_request, device_id, _ROLE_CONTROLLER)

    device = await device_service.get_device(device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено",
        )

    contract = load_contract()
    inert: list[str] = []
    try:
        for selection in body.behaviors:
            inert.extend(validate_behavior(selection.template, selection.params, contract))
    except ParamError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    lifecycle = get_lifecycle_service(http_request)
    # Комната берётся из манифеста. Раньше здесь подставлялась строка
    # "unassigned" на случай отсутствия устройства в манифесте, но такой
    # комнаты в манифесте не бывает: сервис отвечал 400 с текстом про
    # несуществующую комнату вместо объяснения, что не так. Теперь отсутствие
    # комнаты — отдельный отказ с понятным текстом.
    room_id = body.room_id or _room_of_device(lifecycle, device.ha_entity_id)
    if room_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Устройство {device.ha_entity_id} не найдено в манифесте, поэтому "
                "неизвестна его комната. Укажите комнату в поле room_id."
            ),
        )
    behaviors = [
        BehaviorConfig(template=item.template, priority=item.priority, params=item.params)
        for item in body.behaviors
    ]
    try:
        await lifecycle.update_device(device, room_id=room_id, behaviors=behaviors)
    except Exception as error:  # noqa: BLE001 — причина уходит в текст ответа
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось сохранить поведения: {error}",
        ) from error

    # Ответ отдаёт поведения, прочитанные из манифеста ПОСЛЕ записи, а не
    # эхо запроса: если сервис нормализует значения (дополняет умолчания,
    # отбрасывает пустые), пользователь должен увидеть то, что реально сохранено.
    return JSONResponse(
        BehaviorsUpdateResponse(
            device_id=str(device_id),
            behaviors=_device_behaviors(get_lifecycle_service(http_request), device.ha_entity_id),
            inert_params=sorted(set(inert)),
        ).model_dump()
    )
