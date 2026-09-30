"""
API маршруты для управления источниками Home Assistant.

Включает операции создания, получения, удаления и синхронизации источников.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, HttpUrl

from src.core.models.ha_source import HASource
from src.services.device_service import DeviceService


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
    last_sync: str | None
    last_error: str | None
    created_at: str
    updated_at: str


async def get_device_service(request: Request) -> DeviceService:
    """Получает DeviceService из app state."""
    device_service = getattr(request.app.state, "device_service", None)
    if not device_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Device service не инициализирован",
        )
    return device_service


def _source_to_response(source: HASource) -> SourceResponse:
    """Преобразует HASource модель в SourceResponse.

    Args:
        source: Источник из persistence.

    Returns:
        Ответ API с информацией об источнике.
    """
    return SourceResponse(
        id=str(source.id),
        name=source.name,
        # HttpUrl нормализует URL, добавляя '/' в конец (http://host:8123/).
        # Убираем её, чтобы API возвращал URL в том виде, в котором его задал пользователь.
        url=str(source.url).rstrip("/"),
        # Исторически статус "active" использовался вместо "connected" — учитываем оба
        status="connected" if source.status in ("active", "connected") else "disconnected",
        last_sync=source.last_sync.isoformat() if source.last_sync else None,
        last_error=source.last_error,
        created_at=source.created_at.isoformat(),
        updated_at=source.updated_at.isoformat(),
    )


@router.get("", status_code=status.HTTP_200_OK)
async def list_sources(request: Request) -> list[SourceResponse]:
    """Получает список всех источников Home Assistant.

    Returns:
        Список источников
    """
    try:
        persistence = getattr(request.app.state, "persistence", None)
        if not persistence:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persistence не инициализирован",
            )

        sources = await persistence.sources.load_all_sources()
        logger.info(f"Получен список {len(sources)} источников")
        return [_source_to_response(source) for source in sources]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении списка источников: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении списка источников",
        ) from e


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_source(request: Request, req: CreateSourceRequest) -> SourceResponse:
    """Создает новый источник Home Assistant.

    Args:
        request: FastAPI request
        req: Данные источника

    Returns:
        Созданный источник
    """
    try:
        persistence = getattr(request.app.state, "persistence", None)
        if not persistence:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persistence не инициализирован",
            )

        source = HASource(
            id=uuid4(),
            name=req.name,
            url=str(req.url),
            token=req.token,
            # Статус не переопределяем: HASource по умолчанию "disconnected" —
            # источник создан, но ещё не проверен подключением к HA
            last_sync=None,
            last_error=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        await persistence.sources.save_source(source)
        logger.info(f"Создан источник {source.id}: {req.name}")

        return _source_to_response(source)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при создании источника: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при создании источника: {str(e)}",
        ) from e


@router.get("/{source_id}", status_code=status.HTTP_200_OK)
async def get_source(request: Request, source_id: UUID) -> SourceResponse:
    """Получает информацию об источнике.

    Args:
        request: FastAPI request
        source_id: ID источника

    Returns:
        Информация об источнике

    Raises:
        HTTPException: 404 если источник не найден
    """
    try:
        persistence = getattr(request.app.state, "persistence", None)
        if not persistence:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persistence не инициализирован",
            )

        source = await persistence.sources.load_source(source_id)

        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Источник {source_id} не найден",
            )

        return _source_to_response(source)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении источника {source_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении источника",
        ) from e


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(request: Request, source_id: UUID) -> None:
    """Удаляет источник Home Assistant.

    Args:
        request: FastAPI request
        source_id: ID источника для удаления

    Raises:
        HTTPException: 404 если источник не найден
    """
    try:
        persistence = getattr(request.app.state, "persistence", None)
        if not persistence:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persistence не инициализирован",
            )

        source = await persistence.sources.load_source(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Источник {source_id} не найден",
            )

        result = await persistence.sources.delete_source(source_id)
        if result:
            logger.info(f"Удален источник {source_id}")
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось удалить источник",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при удалении источника {source_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при удалении источника",
        ) from e


@router.post("/{source_id}/sync", status_code=status.HTTP_200_OK)
async def sync_source(
    request: Request, source_id: UUID, device_service: DeviceService = Depends(get_device_service)
) -> dict:
    """Запускает синхронизацию устройств из источника.

    Args:
        request: FastAPI request
        source_id: ID источника
        device_service: DeviceService для синхронизации

    Returns:
        Статус синхронизации

    Raises:
        HTTPException: 404 если источник не найден, 500 если ошибка синхронизации
    """
    try:
        persistence = getattr(request.app.state, "persistence", None)
        if not persistence:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Persistence не инициализирован",
            )

        # Проверяем что источник существует
        source = await persistence.sources.load_source(source_id)
        if not source:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Источник {source_id} не найден",
            )

        logger.info(f"Начинаю синхронизацию для источника {source_id}")

        # Запускаем синхронизацию через DeviceService
        devices = await device_service.sync_devices_from_source(source_id)

        logger.info(
            f"Синхронизация завершена для источника {source_id}: загружено {len(devices)} устройств"
        )

        return {
            "status": "success",
            "message": f"Синхронизация завершена. Загружено {len(devices)} устройств",
            "device_count": len(devices),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при синхронизации источника {source_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при синхронизации: {str(e)}",
        ) from e


class AreaInfo(BaseModel):
    """Информация о комнате/области."""

    id: str = Field(description="ID области в HA")
    name: str = Field(description="Название области (комнаты)")
    icon: str | None = Field(None, description="Иконка области")
    picture: str | None = Field(None, description="Изображение области")


class AvailableDevice(BaseModel):
    """Информация об устройстве, доступном для добавления."""

    entity_id: str = Field(description="Entity ID в Home Assistant")
    friendly_name: str = Field(description="Удобное название устройства")
    device_type: str = Field(description="Тип устройства (домен entity_id)")
    area_id: str | None = Field(None, description="ID области (комнаты) в HA")
    area_name: str | None = Field(None, description="Название области (комнаты)")
    state: str = Field(description="Текущее состояние")
    icon: str | None = Field(None, description="Иконка устройства")


class DiscoveryData(BaseModel):
    """Данные для помощи при добавлении устройства."""

    source_id: str = Field(description="ID источника")
    areas: list[AreaInfo] = Field(description="Список доступных комнат в HA")
    available_devices: list[AvailableDevice] = Field(description="Список доступных устройств")
    available_device_count: int = Field(description="Количество доступных устройств в HA")
    error: str | None = Field(
        default=None,
        description=(
            "Причина недоступности источника. Заполняется, когда получить данные "
            "не удалось: интерфейс обязан показать причину, а не «устройств нет» (FR-013)"
        ),
    )


async def _fetch_discovery_data(source: HASource) -> DiscoveryData:
    """Получает устройства и области источника из Home Assistant.

    Используется тот же путь, что и при синхронизации
    (``connect_to_ha`` → ``fetch_devices`` → ``fetch_areas``): он работает в
    автономном режиме и с источниками, созданными в интерфейсе, в отличие от
    глобального WebSocket-адаптера (spec 006, D-006).

    Args:
        source: Источник Home Assistant.

    Returns:
        Данные для мастера; при недоступном источнике — с заполненной причиной.
    """
    from src.adapters.home_assistant.rest_client import HARestClient

    async with HARestClient(source.url, source.token) as rest_client:
        if not await rest_client.connect_to_ha():
            return DiscoveryData(
                source_id=str(source.id),
                areas=[],
                available_devices=[],
                available_device_count=0,
                error=f"Не удалось подключиться к источнику: {source.url}",
            )

        states = await rest_client.fetch_devices()
        areas_raw = await _safe_fetch_areas(rest_client, source)

    areas = [
        AreaInfo(
            id=str(area.get("area_id") or area.get("id") or ""),
            name=str(area.get("name") or ""),
            icon=area.get("icon"),
            picture=area.get("picture"),
        )
        for area in areas_raw
        if area.get("area_id") or area.get("id")
    ]
    area_names = {area.id: area.name for area in areas}

    devices = [
        _to_available_device(state, area_names) for state in states if state.get("entity_id")
    ]

    return DiscoveryData(
        source_id=str(source.id),
        areas=areas,
        available_devices=devices,
        available_device_count=len(devices),
    )


async def _safe_fetch_areas(rest_client: Any, source: HASource) -> list[dict[str, Any]]:
    """Получает области источника, не роняя весь ответ из-за их недоступности.

    Args:
        rest_client: REST-клиент Home Assistant.
        source: Источник (для сообщения в журнале).

    Returns:
        Список областей; пустой список при ошибке.
    """
    try:
        return await rest_client.fetch_areas()
    except Exception as e:
        logger.warning(f"Не удалось получить области источника {source.id}: {e}")
        return []


def _to_available_device(state: dict[str, Any], area_names: dict[str, str]) -> AvailableDevice:
    """Преобразует состояние Home Assistant в элемент ответа мастера.

    Args:
        state: Состояние сущности из Home Assistant.
        area_names: Соответствие идентификаторов областей их названиям.

    Returns:
        Описание доступного устройства.
    """
    attributes = state.get("attributes") or {}
    entity_id = str(state.get("entity_id", ""))
    area_id = attributes.get("area_id")
    return AvailableDevice(
        entity_id=entity_id,
        friendly_name=str(attributes.get("friendly_name") or entity_id),
        device_type=entity_id.split(".")[0],
        area_id=area_id,
        area_name=area_names.get(area_id) if area_id else None,
        state=str(state.get("state", "")),
        icon=attributes.get("icon"),
    )


@router.get("/{source_id}/discovery-data", status_code=status.HTTP_200_OK)
async def get_discovery_data(request: Request, source_id: UUID) -> DiscoveryData:
    """Получает доступные устройства из Home Assistant для помощи при добавлении.

    Args:
        request: HTTP request
        source_id: ID источника

    Returns:
        Данные для мастера: устройства, области и причина недоступности
        источника, если получить данные не удалось (FR-010, FR-013).

    Raises:
        HTTPException: 404 если источник не найден, 503 если persistence недоступен
    """
    persistence = getattr(request.app.state, "persistence", None)
    if not persistence:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persistence не инициализирован",
        )

    source = await persistence.sources.load_source(source_id)
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Источник {source_id} не найден",
        )

    try:
        return await _fetch_discovery_data(source)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении discovery data для источника {source_id}: {e}")
        return DiscoveryData(
            source_id=str(source_id),
            areas=[],
            available_devices=[],
            available_device_count=0,
            error=f"Не удалось получить данные источника: {e}",
        )
