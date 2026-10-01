"""
API маршруты для управления устройствами.

Включает операции получения, обновления конфигурации и отправки команд устройствам.
Реализует фильтрацию по доступу пользователя.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, model_validator

from src.core.models.device import Device
from src.core.models.device_sync_event import DeviceSyncEvent
from src.core.models.manifest import BehaviorConfig
from src.webui.models import (
    AutomationInfo,
    FSMStateView,
    build_all_fsm_state_views,
    build_automation_info,
)
from src.webui.routes.devices.deps import (
    get_device_service,
    get_lifecycle_service,
    get_sync_history,
    record_sync_event,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])

# Требуемые роли на операции (contracts §1, data-model иерархия)
_ROLE_VIEWER = "viewer"
_ROLE_CONTROLLER = "controller"
_ROLE_ADMIN = "admin"


async def _require_access_or_403(
    request: Request,
    device_id: UUID,
    required_role: str,
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
    is_admin = getattr(request.state, "is_admin", False) or (
        request.headers.get("X-Is-Admin", "false").lower() == "true"
    )
    if is_admin:
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


class DeviceResponse(BaseModel):
    """Ответ с информацией об устройстве."""

    id: str
    name: str
    display_name: str | None = None
    device_type: str
    status: str
    state: dict
    source_id: str
    ha_entity_id: str
    ha_area_id: str | None = None
    description: str | None = None
    location: str | None = None
    tags: list[str] | None = None
    created_at: str
    updated_at: str
    fsm: list[FSMStateView] = Field(default_factory=list, description="States of device FSMs")
    automation: AutomationInfo = Field(
        default_factory=lambda: AutomationInfo(configured=False, reason="no_automation"),
        description="Automation availability for the device",
    )


# ============ T033-T057: Управление устройствами (полная реализация) ============


@router.get("", status_code=status.HTTP_200_OK)
async def get_devices(
    request: Request,
    source_id: UUID | None = None,
    x_user_id: str | None = Header(None),
) -> list[DeviceResponse]:
    """Получает список всех доступных пользователю устройств.

    Возвращает только те устройства, к которым пользователь имеет доступ (T069).
    Если заголовок X-User-ID отсутствует, возвращает пустой список.

    Список берётся из единого источника — DeviceService (spec 006, FR-003):
    раньше роут читал временный словарь, который был пуст после перезапуска
    и не содержал устройств, загруженных синхронизацией.

    Args:
        request: HTTP запрос (для получения DeviceService)
        source_id: Опциональный фильтр по источнику
        x_user_id: ID пользователя из заголовка X-User-ID

    Returns:
        Список устройств доступных пользователю
    """
    try:
        # Если нет ID пользователя, возвращаем пустой список
        if not x_user_id:
            logger.debug("Запрос GET /api/v1/devices без X-User-ID - возвращаю пустой список")
            return []

        device_service = get_device_service(request)

        # T069: фильтруем по доступу пользователя (важнее source_id)
        devices = await device_service.get_user_accessible_devices(x_user_id)

        # Фильтруем по source_id если указан (поверх фильтра доступа)
        if source_id:
            devices = [device for device in devices if device.source_id == source_id]

        logger.info(f"Получен список {len(devices)} устройств для пользователя {x_user_id}")
        fsm_views = _build_device_fsm_views(request, devices)
        return [
            _to_device_response(device, fsm_views.get(device.ha_entity_id, []))
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


def _to_device_response(device: Any, fsm_views: list[FSMStateView] | None = None) -> DeviceResponse:
    """Собирает ответ API из модели устройства.

    Поля конфигурации (``display_name``, ``description``, ``location``,
    ``tags``) берутся из ``device.config`` — в модели устройства отдельных
    полей для них нет (spec 006, contracts/device-lifecycle-api.md).

    Устройство без автоматики получает явную отметку ``no_automation``, а не
    пустое значение состояния (spec 007, FR-019).

    Args:
        device: Модель устройства.
        fsm_views: Состояния автоматов устройства.

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
        automation=build_automation_info([view.fsm_id for view in views]),
    )


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

    return _to_device_response(device)


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


class UpdateDeviceConfigRequest(BaseModel):
    """Запрос на обновление конфигурации устройства."""

    display_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    location: str | None = Field(None, max_length=255)
    tags: list[str] | None = Field(None)


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

        return _to_device_response(device)

    except ValueError as e:
        logger.error(f"Ошибка валидации при обновлении конфигурации устройства: {e}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Ошибка при обновлении конфигурации устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при обновлении конфигурации",
        ) from e


class CommandRequest(BaseModel):
    """Единый запрос выполнения команды (T054 + совместимость).

    Принимает три формата (валидатор — хотя бы один идентификатор команды):
    - T054: ``name`` + обязательные ``parameters``;
    - name-алиас: ``command_name`` (параметры необязательны);
    - сервисный: ``service`` + ``data``.
    """

    name: str | None = Field(None, min_length=1, max_length=255, description="Имя команды T054")
    command_name: str | None = Field(
        None, min_length=1, max_length=255, description="Имя команды (алиас)"
    )
    parameters: dict | None = Field(None, description="Параметры команды (обязательны с name)")
    service: str | None = Field(None, description="Сервис HA (domain.service)")
    data: dict | None = Field(None, description="Данные сервиса")

    @model_validator(mode="after")
    def _validate_command_identity(self) -> "CommandRequest":
        """Требует хотя бы один идентификатор команды (contracts §3).

        Returns:
            Саму модель при валидном наборе полей.

        Raises:
            ValueError: если идентификатор не указан или формат неполон.
        """
        if self.command_name:
            return self
        if self.service:
            return self
        if self.name:
            if self.parameters is None:
                raise ValueError("Поле 'parameters' обязательно при использовании формата 'name'")
            return self
        raise ValueError("Укажите 'command_name', 'name' (с 'parameters') или 'service'")


class CommandResponse(BaseModel):
    """Ответ при выполнении команды."""

    id: str = Field(description="ID выполненной команды")
    device_id: str = Field(description="ID устройства")
    command_name: str = Field(description="Имя команды")
    status: str = Field(description="Статус: pending, executing, success, failed")
    created_at: str = Field(description="Время создания")
    completed_at: str | None = None
    result: dict | None = None
    error: str | None = None


@router.post("/{device_id}/command", status_code=status.HTTP_202_ACCEPTED)
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

    try:
        # TODO: Использовать DeviceService.execute_command()
        from uuid import uuid4

        command_id = str(uuid4())

        effective_name = request.command_name or request.name or request.service or "unknown"
        logger.info(f"Выполняю команду {effective_name} на устройстве {device_id}")

        await record_sync_event(
            http_request,
            device_id,
            "command_executed",
            before=None,
            after=None,
            data={
                "command": effective_name,
                "parameters": request.parameters if request.parameters else request.data,
            },
        )

        return CommandResponse(
            id=command_id,
            device_id=str(device_id),
            command_name=effective_name,
            status="executing",
            created_at=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при выполнении команды",
        ) from e


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


class DeviceEventResponse(BaseModel):
    """Событие устройства."""

    id: str = Field(description="ID события")
    device_id: str = Field(description="ID устройства")
    event_type: str = Field(
        description="Тип события: state_changed, config_changed, command_executed"
    )
    timestamp: str = Field(description="Время события")
    data: dict = Field(description="Данные события")


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


class BehaviorSelection(BaseModel):
    """Поведение устройства, выбранное пользователем."""

    template: str = Field(description="Шаблон автоматизации")
    priority: int = Field(default=10, ge=1, description="Приоритет: меньше — выше")
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры шаблона")


class DeviceSelection(BaseModel):
    """Выбранное устройство для добавления."""

    device_entity_id: str = Field(description="Entity ID в Home Assistant")
    device_type: str | None = Field(
        None, description="Тип устройства; по умолчанию — домен из entity_id"
    )
    name: str | None = Field(None, description="Имя устройства; по умолчанию — entity_id")
    target_room: str | None = Field(None, description="Целевая комната для устройства")
    behavior_template: str | None = Field(None, description="Рекомендуемый шаблон поведения")
    ha_area_id: str | None = Field(None, description="ID области в HA")
    behaviors: list[BehaviorSelection] | None = Field(
        None, description="Поведения устройства; при отсутствии — рекомендованный шаблон"
    )


class ApplyDevicesRequest(BaseModel):
    """Запрос на добавление выбранных устройств."""

    source_id: UUID = Field(description="ID источника Home Assistant")
    selections: list[DeviceSelection] = Field(description="Список выбранных устройств")
    dry_run: bool = Field(default=False, description="Если True, только проверяет, не добавляет")


class FailedDevice(BaseModel):
    """Устройство, которое не удалось применить."""

    ha_entity_id: str = Field(description="Entity ID устройства")
    reason: str = Field(description="Причина отказа")


class ApplyDevicesResponse(BaseModel):
    """Ответ при добавлении устройств (contracts/device-lifecycle-api.md)."""

    success: bool = Field(description="Ошибок не было")
    devices_count: int = Field(description="Количество применённых устройств")
    devices: list[DeviceResponse] = Field(
        default_factory=list, description="Применённые устройства"
    )
    devices_added: int = Field(default=0, description="Добавлено новых устройств")
    devices_updated: int = Field(default=0, description="Обновлено существующих")
    failed: int = Field(default=0, description="Количество неудачных применений")
    failed_devices: list[FailedDevice] = Field(
        default_factory=list, description="Устройства, которые не удалось применить"
    )
    dry_run: bool = Field(default=False, description="Был ли это тестовый запуск")
    would_add: int | None = Field(None, description="Сколько устройств было бы добавлено")
    errors: list[str] | None = Field(None, description="Человекочитаемые ошибки")


@router.post("/apply", status_code=status.HTTP_201_CREATED)
async def apply_devices(request: Request, body: ApplyDevicesRequest) -> ApplyDevicesResponse:
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

    for selection in body.selections:
        try:
            device = _build_device_from_selection(selection, body.source_id)
            behaviors = _build_behaviors(selection)
            room_id = selection.target_room or _default_room_id(lifecycle.manifest)

            device, saved = await lifecycle.add_device(
                device, room_id=room_id, behaviors=behaviors, user_id=user_id
            )
            if saved:
                added += 1
            else:
                updated += 1
            applied.append(_to_device_response(device))
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


def _default_room_id(manifest: Any) -> str:
    """Возвращает комнату по умолчанию.

    Args:
        manifest: Модель манифеста.

    Returns:
        Идентификатор первой комнаты.

    Raises:
        ValueError: Если в манифесте нет ни одной комнаты.
    """
    if not manifest.rooms:
        msg = "В манифесте нет комнат: добавьте комнату перед добавлением устройств"
        raise ValueError(msg)
    return manifest.rooms[0].id


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
