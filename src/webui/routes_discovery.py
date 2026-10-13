"""Служебные маршруты веб-слоя: список комнат для интерфейса.

Прежний мастер обнаружения устройств (страницы и маршруты ``/discovery/*``)
удалён вместе со старым серверным интерфейсом. Мастер обнаружения нового
интерфейса работает через ``/api/v1/devices/sources/*`` и
``/api/v1/devices/apply``; здесь остаётся только справочник комнат манифеста,
который нужен форме импорта.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger


if TYPE_CHECKING:
    from core.persistence.manifest_store import ManifestStore

router = APIRouter()

_manifest_path: str | None = None
_manifest_store: ManifestStore | None = None


def init_discovery_routes(
    manifest_path: str,
    manifest_store: ManifestStore | None = None,
) -> None:
    """Запомнить хранилище манифеста для справочника комнат.

    Args:
        manifest_path: Путь к файлу манифеста.
        manifest_store: Хранилище манифеста приложения — чтобы список комнат
            совпадал с тем, что показывает остальной интерфейс.
    """
    global _manifest_path, _manifest_store
    _manifest_path = manifest_path
    _manifest_store = manifest_store
    logger.info(f"Room reference initialized with manifest: {manifest_path}")


@router.get("/api/rooms")
async def get_rooms() -> JSONResponse:
    """Список комнат манифеста для выбора при импорте устройств.

    Returns:
        JSON ``{"rooms": [{"id", "name"}]}`` либо 503, если манифест ещё не
        подключён.

    Raises:
        HTTPException: 503, если хранилище манифеста не инициализировано,
            500 при ошибке чтения.
    """
    if _manifest_path is None:
        raise HTTPException(status_code=503, detail="Manifest path not initialized")

    try:
        if _manifest_store is None:
            return JSONResponse(content={"rooms": []})
        if _manifest_store.current is None:
            _manifest_store.load()

        # cast() — только типовое уточнение: load() выше гарантирует,
        # что current заполнен.
        rooms = [
            {"id": room.id, "name": room.name} for room in cast(Any, _manifest_store.current).rooms
        ]
        return JSONResponse(content={"rooms": rooms})
    except Exception as e:
        logger.error(f"Failed to get rooms: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
