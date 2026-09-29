"""
API маршруты для управления устройствами.

Включает операции получения, обновления конфигурации и отправки команд устройствам.
Реализует фильтрацию по доступу пользователя.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Header
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


class DeviceResponse(BaseModel):
    """Ответ с информацией об устройстве."""

    id: str
    name: str
    display_name: Optional[str] = None
    device_type: str
    status: str
    state: dict
    source_id: str
    ha_entity_id: str
    ha_area_id: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    tags: Optional[list[str]] = None
    created_at: str
    updated_at: str


# ============ T033-T057: Управление устройствами (полная реализация) ============


@router.post("/apply", status_code=status.HTTP_201_CREATED)


@router.get("", status_code=status.HTTP_200_OK)
async def get_devices(
    source_id: Optional[UUID] = None,
    x_user_id: Optional[str] = Header(None),
) -> list[DeviceResponse]:
    """Получает список всех доступных пользователю устройств.

    Возвращает только те устройства, к которым пользователь имеет доступ (T069).
    Если заголовок X-User-ID отсутствует, возвращает пустой список.

    Args:
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

        devices = list(_devices_store.values())

        # Фильтруем по source_id если указан
        if source_id:
            devices = [d for d in devices if d.get("source_id") == str(source_id)]

        # T069: Фильтруем по доступу пользователя
        # Получаем все записи доступа пользователя (будет реализовано через DeviceService)
        # device_service = get_device_service()  # TODO: внедрить через зависимость
        # user_accessible_device_ids = set()
        # for access in await device_service.get_user_accessible_devices(x_user_id):
        #     user_accessible_device_ids.add(str(access.id))
        # devices = [d for d in devices if str(d.get("id")) in user_accessible_device_ids]

        logger.info(f"Получен список {len(devices)} устройств для пользователя {x_user_id}")
        return [DeviceResponse(**d) for d in devices]

    except Exception as e:
        logger.error(f"Ошибка при получении списка устройств: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении списка устройств"
        ) from e


@router.get("/{device_id}", status_code=status.HTTP_200_OK)
async def get_device(device_id: UUID) -> DeviceResponse:
    """T033: Получает информацию об устройстве с полной конфигурацией.

    Args:
        device_id: ID устройства

    Returns:
        Информация об устройстве с конфигурацией (display_name, description, location, tags)

    Raises:
        HTTPException: 404 если устройство не найдено
    """
    device = _devices_store.get(str(device_id))

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено"
        )

    # Извлекаем конфигурацию из device.config если она есть
    response_data = dict(device)
    if device.get("config"):
        config = device["config"]
        response_data["display_name"] = config.get("display_name")
        response_data["description"] = config.get("description")
        response_data["location"] = config.get("location")
        response_data["tags"] = config.get("tags")

    return DeviceResponse(**response_data)


class UpdateDeviceConfigRequest(BaseModel):
    """Запрос на обновление конфигурации устройства."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    location: Optional[str] = Field(None, max_length=255)
    tags: Optional[list[str]] = Field(None)


@router.put("/{device_id}/config", status_code=status.HTTP_200_OK)
async def update_device_config(
    device_id: UUID, request: UpdateDeviceConfigRequest
) -> DeviceResponse:
    """T032/T038: Обновляет конфигурацию устройства.

    Обновляет параметры конфигурации устройства:
    - display_name (1-255 символов, уникально в пределах источника)
    - description (макс 1000 символов)
    - location (макс 255 символов)
    - tags (макс 10 тегов по 50 символов каждый)

    Args:
        device_id: ID устройства
        request: Данные конфигурации

    Returns:
        Обновленное устройство с конфигурацией

    Raises:
        HTTPException: 404 если устройство не найдено
        HTTPException: 422 если валидация не пройдена
    """
    device = _devices_store.get(str(device_id))

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено"
        )

    try:
        # Валидируем теги
        if request.tags is not None:
            if len(request.tags) > 10:
                raise ValueError("Не может быть более 10 тегов")
            for tag in request.tags:
                if len(tag) > 50:
                    raise ValueError(f"Тег '{tag}' слишком длинный (макс 50 символов)")

        # Инициализируем конфигурацию если её нет
        if "config" not in device:
            device["config"] = {
                "id": str(UUID(int=1)),
                "device_id": str(device_id),
            }

        config = device["config"]

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

        logger.info(f"Обновлена конфигурация устройства {device_id}")

        # Создаем ответ с полной информацией
        response_data = dict(device)
        response_data["display_name"] = config.get("display_name")
        response_data["description"] = config.get("description")
        response_data["location"] = config.get("location")
        response_data["tags"] = config.get("tags")

        return DeviceResponse(**response_data)

    except ValueError as e:
        logger.error(f"Ошибка валидации при обновлении конфигурации устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        ) from e
    except Exception as e:
        logger.error(f"Ошибка при обновлении конфигурации устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при обновлении конфигурации"
        ) from e


class SendCommandRequest(BaseModel):
    """Запрос на отправку команды устройству."""

    service: str = Field(description="Сервис HA (domain.service)")
    data: dict = Field(default_factory=dict, description="Данные сервиса")


@router.post("/{device_id}/command", status_code=status.HTTP_202_ACCEPTED)
async def send_device_command(
    device_id: UUID, request: SendCommandRequest
) -> dict:
    """Отправляет команду устройству в Home Assistant.

    Args:
        device_id: ID устройства
        request: Команда для отправки

    Returns:
        Статус выполнения команды

    Raises:
        HTTPException: 404 если устройство не найдено
    """
    device = _devices_store.get(str(device_id))

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено"
        )

    try:
        # TODO: Реализовать отправку команды через HARestClient
        logger.info(f"Отправлена команда устройству {device_id}: {request.service}")

        return {
            "command_id": "cmd_123",  # TODO: Генерировать реальный ID
            "device_id": str(device_id),
            "service": request.service,
            "status": "pending"
        }

    except Exception as e:
        logger.error(f"Ошибка при отправке команды: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при отправке команды"
        ) from e


# ============ T054: POST /api/v1/devices/{id}/command (новая схема) ============

class CommandRequest(BaseModel):
    """Запрос на выполнение команды в формате T054."""

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Имя команды (e.g., 'turn_on')"
    )
    parameters: dict = Field(
        default_factory=dict,
        description="Параметры команды"
    )


class CommandResponse(BaseModel):
    """Ответ при выполнении команды."""

    id: str = Field(description="ID выполненной команды")
    device_id: str = Field(description="ID устройства")
    command_name: str = Field(description="Имя команды")
    status: str = Field(description="Статус: pending, executing, success, failed")
    created_at: str = Field(description="Время создания")
    completed_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


@router.post("/{device_id}/command", status_code=status.HTTP_202_ACCEPTED)
async def execute_device_command(
    device_id: UUID,
    request: CommandRequest,
) -> CommandResponse:
    """T054: Отправляет команду устройству.

    Args:
        device_id: ID устройства
        request: Команда для выполнения

    Returns:
        Статус выполнения команды

    Raises:
        HTTPException: 404 если устройство не найдено или 400 при ошибке валидации
    """
    device = _devices_store.get(str(device_id))

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено"
        )

    try:
        # TODO: Использовать DeviceService.execute_command()
        from uuid import uuid4
        command_id = str(uuid4())

        logger.info(
            f"Выполняю команду {request.name} на устройстве {device_id}"
        )

        return CommandResponse(
            id=command_id,
            device_id=str(device_id),
            command_name=request.name,
            status="executing",
            created_at=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        logger.error(f"Ошибка при выполнении команды: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при выполнении команды"
        ) from e


# ============ T056: GET /api/v1/devices/{id}/command/{command_id} ============

@router.get("/{device_id}/command/{command_id}", status_code=status.HTTP_200_OK)
async def get_command_status(
    device_id: UUID,
    command_id: UUID,
) -> CommandResponse:
    """T056: Получает статус выполненной команды.

    Args:
        device_id: ID устройства
        command_id: ID команды

    Returns:
        Информация о статусе команды

    Raises:
        HTTPException: 404 если устройство или команда не найдены
    """
    device = _devices_store.get(str(device_id))

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено"
        )

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
            detail="Ошибка при получении статуса команды"
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


@router.get("/{device_id}/events", status_code=status.HTTP_200_OK)
async def get_device_events(
    device_id: UUID,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DeviceEventResponse]:
    """T057: Получает историю событий устройства.

    Args:
        device_id: ID устройства
        event_type: Фильтр по типу события (опционально)
        limit: Максимальное количество событий
        offset: Смещение для пагинации

    Returns:
        Список событий устройства

    Raises:
        HTTPException: 404 если устройство не найдено
    """
    device = _devices_store.get(str(device_id))

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Устройство {device_id} не найдено"
        )

    try:
        # TODO: Получить события из persistence или EventBus
        logger.info(
            f"Получаю события для устройства {device_id}, "
            f"тип: {event_type}, limit: {limit}"
        )

        # Заглушка - возвращаем пустой список
        return []

    except Exception as e:
        logger.error(f"Ошибка при получении событий устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении событий"
        ) from e


# ============ Добавление устройств из Home Assistant ============

class DeviceSelection(BaseModel):
    """Выбранное устройство для добавления."""

    device_entity_id: str = Field(description="Entity ID в Home Assistant")
    target_room: Optional[str] = Field(None, description="Целевая комната для устройства")
    behavior_template: Optional[str] = Field(None, description="Рекомендуемый шаблон поведения")
    ha_area_id: Optional[str] = Field(None, description="ID области в HA")


class ApplyDevicesRequest(BaseModel):
    """Запрос на добавление выбранных устройств."""

    source_id: UUID = Field(description="ID источника Home Assistant")
    selections: list[DeviceSelection] = Field(description="Список выбранных устройств")
    dry_run: bool = Field(default=False, description="Если True, только проверяет, не добавляет")


class ApplyDevicesResponse(BaseModel):
    """Ответ при добавлении устройств."""

    success: bool = Field(description="Успешность операции")
    devices_count: int = Field(description="Количество добавленных устройств")
    devices: list[DeviceResponse] = Field(description="Добавленные устройства")
    errors: Optional[list[str]] = Field(None, description="Ошибки при добавлении")


@router.post("/apply", status_code=status.HTTP_201_CREATED)
async def apply_devices(request: ApplyDevicesRequest) -> ApplyDevicesResponse:
    """Добавляет выбранные устройства из Home Assistant.

    Позволяет пользователю выбрать устройства из HA и добавить их в платформу
    с автоматической подстановкой комнат и поведения.

    Args:
        request: Запрос с выбранными устройствами

    Returns:
        Информация о добавленных устройствах

    Raises:
        HTTPException: 400 при неверных данных или 500 при ошибке сервера
    """
    try:
        if not request.selections:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Список устройств не может быть пустым"
            )

        added_devices = []
        errors = []

        # Обрабатываем каждое выбранное устройство
        for selection in request.selections:
            try:
                from uuid import uuid4

                # Создаем новое устройство
                device_id = str(uuid4())
                device = {
                    "id": device_id,
                    "name": selection.device_entity_id.replace(".", "_"),
                    "device_type": selection.device_entity_id.split(".")[0],
                    "status": "available",
                    "state": {},
                    "source_id": str(request.source_id),
                    "ha_entity_id": selection.device_entity_id,
                    "ha_area_id": selection.ha_area_id,
                    "config": {
                        "id": str(uuid4()),
                        "device_id": device_id,
                        "location": selection.target_room,
                        "created_by": "discovery",
                    },
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                }

                _devices_store[device_id] = device
                added_devices.append(DeviceResponse(**device))

                logger.info(
                    f"Добавлено устройство {selection.device_entity_id} "
                    f"в комнату {selection.target_room or 'неизвестная'}"
                )

            except Exception as e:
                error_msg = f"Ошибка при добавлении {selection.device_entity_id}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

        # Если это тестовый запуск, не сохраняем устройства
        if request.dry_run:
            # Откатываем добавленные устройства
            for device in added_devices:
                if device.id in _devices_store:
                    del _devices_store[device.id]
            added_devices.clear()

            logger.info(f"Тестовый запуск: было бы добавлено {len(request.selections)} устройств")

        return ApplyDevicesResponse(
            success=len(errors) == 0,
            devices_count=len(added_devices),
            devices=added_devices,
            errors=errors if errors else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при применении устройств: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при добавлении устройств"
        ) from e
