"""
API маршруты для управления источниками Home Assistant.

Включает операции создания, получения и синхронизации источников.
"""

import logging
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/devices/sources", tags=["sources"])


class CreateSourceRequest(BaseModel):
    """Запрос на создание источника HA."""

    name: str = Field(min_length=1, max_length=255, description="Название источника")
    url: HttpUrl = Field(description="URL Home Assistant")
    token: str = Field(min_length=10, description="API токен HA")


class SourceResponse(BaseModel):
    """Ответ с информацией об источнике."""

    id: str
    name: str
    url: str
    status: str
    last_sync: Optional[str]
    last_error: Optional[str]
    created_at: str
    updated_at: str


# Хранилище источников (временное, будет использовать persistence)
_sources_store: dict = {}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_source(request: CreateSourceRequest) -> SourceResponse:
    """Создает новый источник Home Assistant.

    Args:
        request: Данные источника

    Returns:
        Созданный источник
    """
    try:
        source_id = str(uuid4())
        source_data = {
            "id": source_id,
            "name": request.name,
            "url": str(request.url),
            "token": request.token,
            "status": "disconnected",
            "last_sync": None,
            "last_error": None,
            "created_at": "2026-09-29T00:00:00",
            "updated_at": "2026-09-29T00:00:00",
        }

        _sources_store[source_id] = source_data
        logger.info(f"Создан источник {source_id}: {request.name}")

        return SourceResponse(**source_data)

    except Exception as e:
        logger.error(f"Ошибка при создании источника: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при создании источника: {str(e)}"
        ) from e


@router.get("/{source_id}", status_code=status.HTTP_200_OK)
async def get_source(source_id: UUID) -> SourceResponse:
    """Получает информацию об источнике.

    Args:
        source_id: ID источника

    Returns:
        Информация об источнике

    Raises:
        HTTPException: 404 если источник не найден
    """
    source = _sources_store.get(str(source_id))

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Источник {source_id} не найден"
        )

    return SourceResponse(**source)


@router.post("/{source_id}/sync", status_code=status.HTTP_200_OK)
async def sync_source(source_id: UUID) -> dict:
    """Запускает синхронизацию устройств из источника.

    Args:
        source_id: ID источника

    Returns:
        Статус синхронизации

    Raises:
        HTTPException: 404 если источник не найден
    """
    source = _sources_store.get(str(source_id))

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Источник {source_id} не найден"
        )

    try:
        logger.info(f"Начинаю синхронизацию для источника {source_id}")

        # TODO: Реализовать синхронизацию через HARestClient и DeviceService
        # 1. Подключиться к HA
        # 2. Получить список устройств
        # 3. Сохранить в persistence
        # 4. Опубликовать события

        source["status"] = "connecting"

        return {
            "status": source["status"],
            "message": f"Синхронизация запущена для источника {source_id}"
        }

    except Exception as e:
        logger.error(f"Ошибка при синхронизации источника {source_id}: {e}")
        source["status"] = "error"
        source["last_error"] = str(e)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при синхронизации: {str(e)}"
        ) from e


class AreaInfo(BaseModel):
    """Информация о комнате/области."""

    id: str = Field(description="ID области в HA")
    name: str = Field(description="Название области (комнаты)")
    icon: Optional[str] = Field(None, description="Иконка области")
    picture: Optional[str] = Field(None, description="Изображение области")


class AvailableDevice(BaseModel):
    """Информация об устройстве, доступном для добавления."""

    entity_id: str = Field(description="Entity ID в Home Assistant")
    friendly_name: str = Field(description="Удобное название устройства")
    device_type: str = Field(description="Тип устройства (домен entity_id)")
    area_id: Optional[str] = Field(None, description="ID области (комнаты) в HA")
    area_name: Optional[str] = Field(None, description="Название области (комнаты)")
    state: str = Field(description="Текущее состояние")
    icon: Optional[str] = Field(None, description="Иконка устройства")


class DiscoveryData(BaseModel):
    """Данные для помощи при добавлении устройства."""

    source_id: str = Field(description="ID источника")
    areas: list[AreaInfo] = Field(description="Список доступных комнат в HA")
    available_devices: list[AvailableDevice] = Field(description="Список доступных устройств")
    available_device_count: int = Field(description="Количество доступных устройств в HA")


@router.get("/{source_id}/discovery-data", status_code=status.HTTP_200_OK)
async def get_discovery_data(source_id: UUID) -> DiscoveryData:
    """Получает вспомогательные данные для добавления устройства из HA источника.

    Возвращает список доступных комнат, доступные устройства и другую информацию для помощи пользователю
    при добавлении нового устройства с правильной подстановкой комнаты.

    Args:
        source_id: ID источника Home Assistant

    Returns:
        Данные для помощи при добавлении устройства

    Raises:
        HTTPException: 404 если источник не найден или 503 при ошибке подключения к HA
    """
    source = _sources_store.get(str(source_id))

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Источник {source_id} не найден"
        )

    try:
        from src.adapters.home_assistant.rest_client import HARestClient

        # Получаем данные из HA
        async with HARestClient(source["url"], source["token"]) as client:
            # Подключаемся к HA
            connected = await client.connect_to_ha()
            if not connected:
                raise Exception("Не удалось подключиться к Home Assistant")

            # Получаем области (комнаты)
            areas_data = await client.fetch_areas()
            areas_map = {
                area.get("id", ""): AreaInfo(
                    id=area.get("id", ""),
                    name=area.get("name", ""),
                    icon=area.get("icon"),
                    picture=area.get("picture"),
                )
                for area in areas_data
            }
            areas = list(areas_map.values())

            # Получаем устройства и их области
            devices_data = await client.fetch_devices()
            device_registry = await client.fetch_device_registry()

            # Создаем map device_id -> area_id из реестра
            device_to_area = {}
            for device in device_registry:
                device_id = device.get("id", "")
                area_id = device.get("area_id")
                if device_id and area_id:
                    device_to_area[device_id] = area_id

            # Парсим доступные устройства
            available_devices = []
            for state_obj in devices_data:
                try:
                    entity_id = state_obj.get("entity_id", "")
                    if not entity_id or entity_id.startswith("automation."):
                        continue

                    domain = entity_id.split(".")[0]
                    # Пропускаем системные сущности
                    if domain in ["automation", "script", "scene", "update"]:
                        continue

                    attributes = state_obj.get("attributes", {})
                    friendly_name = attributes.get("friendly_name", entity_id)

                    # Пытаемся найти area_id из реестра устройств
                    area_id = None
                    area_name = None
                    device_id = attributes.get("device_id")
                    if device_id and device_id in device_to_area:
                        area_id = device_to_area[device_id]
                        if area_id in areas_map:
                            area_name = areas_map[area_id].name

                    available_devices.append(AvailableDevice(
                        entity_id=entity_id,
                        friendly_name=friendly_name,
                        device_type=domain,
                        area_id=area_id,
                        area_name=area_name,
                        state=state_obj.get("state", "unknown"),
                        icon=attributes.get("icon"),
                    ))
                except Exception as e:
                    logger.warning(f"Ошибка при парсинге устройства {state_obj}: {e}")
                    continue

            logger.info(
                f"Загружены данные для добавления устройства: "
                f"{len(areas)} комнат, {len(available_devices)} устройств"
            )

            return DiscoveryData(
                source_id=str(source_id),
                areas=areas,
                available_devices=available_devices,
                available_device_count=len(available_devices),
            )

    except Exception as e:
        logger.error(f"Ошибка при получении данных для добавления устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Ошибка при подключении к Home Assistant: {str(e)}"
        ) from e
