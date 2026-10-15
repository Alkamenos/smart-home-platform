"""
API маршруты для управления устройствами.

Включает операции получения, обновления конфигурации и отправки команд устройствам.
Реализует фильтрацию по доступу пользователя.
"""

import contextlib
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from core.models.manifest import BehaviorConfig
from webui.models import build_all_fsm_state_views
from webui.routes.devices.access_control import require_admin
from webui.routes.devices.deps import (
    get_device_service,
    get_lifecycle_service,
    get_sync_history,
    record_sync_event,
)
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
from webui.services.decisions import decision_view


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])

# Требуемые роли на операции (contracts §1, data-model иерархия)
# Literal-типизация: DeviceService принимает роли как Literal["viewer", ...],
# а значения ниже — единственные, которые вообще передаются в проверку доступа.
_ROLE_VIEWER: Literal["viewer"] = "viewer"
_ROLE_CONTROLLER: Literal["controller"] = "controller"
_ROLE_ADMIN: Literal["admin"] = "admin"


def _is_admin_request(request: Request) -> bool:
    """Определяет, помечен ли запрос как пришедший от глобального администратора.

    Единая точка чтения признака для всех device-endpoints: и для одиночных
    операций (`_require_access_or_403`), и для списка устройств. Берётся из
    ``request.state`` (заполнил middleware) с фоллбэком на заголовок
    ``X-Is-Admin`` — сам список middleware не проходит, поэтому заголовок для
    него остаётся единственным источником.

    Args:
        request: HTTP запрос

    Returns:
        True, если запрос помечен как от глобального администратора.
    """
    is_admin: bool = getattr(request.state, "is_admin", False)
    return is_admin or (request.headers.get("X-Is-Admin", "false").lower() == "true")


async def _require_access_or_403(
    request: Request,
    device_id: UUID,
    required_role: Literal["viewer", "controller", "admin"],
) -> None:
    """Проверяет роль пользователя на операцию над устройством (US1/T006).

    Идентификация берётся из request.state (заполнил middleware) с фоллбэком
    на заголовки. Не-админ без записи доступа (роль ниже требуемой) → 403.

    Args:
        request: HTTP запрос
        device_id: ID устройства
        required_role: Минимальная роль (viewer/controller/admin)

    Raises:
        HTTPException: 403 если доступ не пройден.
    """
    user_id = getattr(request.state, "user_id", None) or request.headers.get("X-User-ID")
    if _is_admin_request(request):
        return
    if not user_id:
        # Middleware уже отбил бы такой запрос; страховка
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-User-ID header"
        )
    service = get_device_service(request)
    allowed = await service.check_device_access(device_id, user_id, required_role=required_role)
    if not allowed:
        logger.warning(
            f"Access denied: user {user_id} -> device {device_id} (requires {required_role})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )


# ============ T033-T057: Управление устройствами (полная реализация) ============


@router.get("", status_code=status.HTTP_200_OK)
async def get_devices(
    request: Request,
    source_id: UUID | None = None,
    ha_entity_id: str | None = None,
    x_user_id: str | None = Header(None),
) -> list[DeviceResponse]:
    """Получает список всех доступных пользователю устройств.

    Видимость определяется признаком администратора и, для остальных, записями
    о доступе (T069, contracts/access-control-api.md §2):

    - ``X-Is-Admin: true`` → все устройства установки без фильтрации по
      записям: администратор глобальный, персональные записи ему не нужны
      (spec 004 spec.md:128, data-model.md:38). Тот же обход, что даёт
      одиночным операциям `_require_access_or_403` — иначе в одном модуле
      действовали бы два противоречивых правила «кто имеет право видеть
      устройство», а дефолтная идентичность WebUI (администратор,
      ``src/webui/app.py``) получала бы от своего же API пустой список.
    - иначе — только устройства, к которым у пользователя есть запись о доступе
      (``get_user_accessible_devices``); без ``X-User-ID`` пустой список.

    Фильтры по ``source_id`` и ``ha_entity_id`` применяются поверх в обоих
    случаях. Фильтр по ``ha_entity_id`` был молчаливо игнорируем: параметр
    приходил в запрос, но на выборку не влиял, и вызывающий код получал все
    устройства, считая, что получил суженную выборку (#74).

    Список берётся из единого источника — DeviceService (spec 006, FR-003):
    раньше роут читал временный словарь, который был пуст после перезапуска
    и не содержал устройств, загруженных синхронизацией.

    Args:
        request: HTTP запрос (для получения DeviceService и признака админа)
        source_id: Опциональный фильтр по источнику
        ha_entity_id: Опциональный фильтр по entity_id в Home Assistant
        x_user_id: ID пользователя из заголовка X-User-ID

    Returns:
        Список устройств, доступных пользователю
    """
    try:
        device_service = get_device_service(request)
        is_admin = _is_admin_request(request)

        if is_admin:
            # Обход администратора: полный список без чтения записей доступа.
            devices = await device_service.list_devices()
        else:
            # Если нет ID пользователя, возвращаем пустой список
            if not x_user_id:
                logger.debug("Запрос GET /api/v1/devices без X-User-ID - возвращаю пустой список")
                return []

            # T069: фильтруем по доступу пользователя (важнее source_id)
            devices = await device_service.get_user_accessible_devices(x_user_id)

        # Фильтры применяются поверх фильтра доступа, а не вместо него.
        if source_id:
            devices = [device for device in devices if device.source_id == source_id]
        if ha_entity_id:
            devices = [device for device in devices if device.ha_entity_id == ha_entity_id]

        logger.info(
            f"Получен список {len(devices)} устройств для пользователя {x_user_id} "
            f"(администратор: {is_admin})"
        )
        fsm_views = _build_device_fsm_views(request, devices)
        behaviors_map = _build_device_behaviors_map(request, devices)
        return [
            _to_device_response(
                device,
                fsm_views.get(device.ha_entity_id, []),
                behaviors_map.get(device.ha_entity_id, []),
            )
            for device in devices
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении списка устройств: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении списка устройств",
        ) from e


@router.get("/{device_id}", status_code=status.HTTP_200_OK)
async def get_device(request: Request, device_id: UUID) -> DeviceResponse:
    """T033: Получает информацию об устройстве с полной конфигурацией.

    Args:
        request: HTTP запрос (идентификация из middleware)
        device_id: ID устройства

    Returns:
        Информация об устройстве с конфигурацией (display_name, description, location, tags)

    Raises:
        HTTPException: 403 если нет роли viewer; 404 если устройство не найдено
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_VIEWER)

    # Состояния автоматов и последнее решение: без них страница прибора не
    # отвечает на «почему так» (спека 017, US3). Ключи решения — идентификаторы
    # автоматов устройства и его сущность.
    container = getattr(request.app.state, "container", None)
    engine = getattr(container, "fsm", None)
    fsm_views = build_all_fsm_state_views(engine, {device.ha_entity_id}) if engine else []
    decision = decision_view(engine, [view.fsm_id for view in fsm_views] + [device.ha_entity_id])

    return _to_device_response(
        device,
        fsm_views=fsm_views,
        behaviors=_device_behaviors(get_lifecycle_service(request), device.ha_entity_id),
        decision=decision,
    )


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(request: Request, device_id: UUID) -> Response:
    """T040: Полностью удаляет устройство (spec 006, US4).

    Каскад выполняет сервис жизненного цикла: снятие машин состояний →
    отзыв прав → удаление из хранилища, кэша и индексов → удаление из
    манифеста → перестроение маршрутизации → аудит. Повторное удаление
    считается успехом (FR-027), неизвестное устройство — 404 (FR-025).

    Args:
        request: HTTP запрос (идентификация из middleware)
        device_id: ID устройства

    Returns:
        204 без тела

    Raises:
        HTTPException: 403 без прав администратора, 404 если устройство не найдено,
            500 если сервис жизненного цикла недоступен
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)
    if not device:
        # Повторное удаление — успех (идемпотентность), неизвестный id — 404
        if device_service.was_device_deleted(device_id):
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_ADMIN)

    lifecycle_service = get_lifecycle_service(request)
    if lifecycle_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис жизненного цикла устройств недоступен",
        )

    user_id = (
        getattr(request.state, "user_id", None) or request.headers.get("X-User-ID") or "system"
    )
    try:
        await lifecycle_service.delete_device(device, user_id=user_id)
    except ValueError as e:
        logger.warning(f"Не удалось удалить устройство {device_id}: {e}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Ошибка удаления устройства {device_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось удалить устройство",
        ) from e

    logger.info(f"Устройство удалено через API: {device.ha_entity_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


_MANUAL_FSM_EVENTS: dict[str, str] = {
    "turn_on": "manual_switch_on",
    "turn_off": "manual_switch_off",
}
"""Команды, имеющие событие автомата.

Совпадение имён здесь намеренное: шаблоны объявляют переходы по событиям
``manual_switch_on``/``manual_switch_off``, и это единственные ручные события,
объявленные хоть в каком-то шаблоне (`lighting`, `night_light`). Для остальных
команд события нет — команда уходит в Home Assistant напрямую, и ответ сообщает,
что состояние автомата не отслежено (Known Issue #69).
"""


@router.post("/{device_id}/command", status_code=status.HTTP_200_OK)
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


@router.get("/{device_id}/command/{command_id}", status_code=status.HTTP_200_OK)
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


@router.get("/{device_id}/events", status_code=status.HTTP_200_OK)
async def get_device_events(
    device_id: UUID,
    request: Request,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DeviceEventResponse]:
    """T057: Получает историю событий устройства.

    Args:
        device_id: ID устройства
        request: HTTP запрос (идентификация из middleware)
        event_type: Фильтр по типу события (опционально)
        limit: Максимальное количество событий
        offset: Смещение для пагинации

    Returns:
        Список событий устройства

    Raises:
        HTTPException: 403 если нет роли viewer; 404 если устройство не найдено
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_VIEWER)

    try:
        history = get_sync_history(request)
        if history is None:
            logger.warning(f"История операций недоступна для устройства {device_id}")
            return []

        events = await history.list_events(device_id, action=event_type, limit=limit, offset=offset)
        return [_to_event_response(event) for event in events]

    except Exception as e:
        logger.error(f"Ошибка при получении событий устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка при получении событий"
        ) from e


# ============ Добавление устройств из Home Assistant ============


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
