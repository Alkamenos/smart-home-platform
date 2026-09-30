"""Routes for Device Discovery Wizard."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger


if TYPE_CHECKING:
    from src.adapters.ha_adapter import HAAdapter
    from src.core.persistence.manifest_store import ManifestStore

router = APIRouter()

_discovery_service = None
_manifest_path: str | None = None
_manifest_store: ManifestStore | None = None


def init_discovery_routes(
    ha_adapter: HAAdapter,
    manifest_path: str,
    manifest_store: ManifestStore | None = None,
) -> None:
    """Инициализирует сервис обнаружения с адаптером и хранилищем манифеста.

    Args:
        ha_adapter: Адаптер Home Assistant для сканирования сущностей.
        manifest_path: Путь к файлу манифеста.
        manifest_store: Хранилище манифеста приложения. Передаётся, чтобы
            применение из мастера обновляло то же состояние, что и веб-интерфейс.
    """
    global _discovery_service, _manifest_path, _manifest_store
    from src.core.discovery.discovery_service import DeviceDiscoveryService

    _discovery_service = DeviceDiscoveryService(ha_adapter, manifest_store=manifest_store)
    _manifest_path = manifest_path
    _manifest_store = manifest_store
    logger.info(f"Discovery routes initialized with manifest: {manifest_path}")


@router.get("/discovery", response_class=HTMLResponse)
async def discovery_page(request: Request) -> HTMLResponse:
    """Отдаёт страницу мастера добавления устройств.

    Шаблоны поведений и категории берутся у бэкенда, а не зашиваются в
    JavaScript: мастер обязан предлагать только то, что платформа
    действительно поддерживает (spec 006, T031).

    Args:
        request: HTTP-запрос.

    Returns:
        Отрисованная страница мастера.
    """
    template_dir = Path(__file__).parent / "templates"
    from fastapi.templating import Jinja2Templates

    from src.core.discovery.classifier import DeviceClassifier
    from src.webui.template_loader import get_template_loader

    templates = Jinja2Templates(directory=str(template_dir))
    template_names = sorted(get_template_loader().load_all().keys())

    return templates.TemplateResponse(
        request,
        "discovery.html",
        {
            "user_id": getattr(request.app.state, "default_user_id", None) or "admin_user",
            "user_is_admin": bool(getattr(request.app.state, "default_user_is_admin", False)),
            "available_templates": template_names,
            "categories": {
                domain: category.value for domain, category in DeviceClassifier.DOMAIN_MAP.items()
            },
        },
    )


@router.post("/discovery/scan")
async def scan_devices(
    page: int = Form(1),
    page_size: int = Form(25),
    filter_domain: str | None = Form(None),
    filter_category: str | None = Form(None),
    filter_area: str | None = Form(None),
) -> JSONResponse:
    """Scan devices from Home Assistant with pagination and filters."""
    if _discovery_service is None:
        raise HTTPException(status_code=503, detail="Discovery service not initialized")

    try:
        result = await _discovery_service.scan_devices(
            page=page,
            page_size=page_size,
            filter_domain=filter_domain,
            filter_category=filter_category,
            filter_area=filter_area,
        )
        return JSONResponse(content=result)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/discovery/apply")
async def bulk_apply(
    include_all: bool = Form(False),
    auto_apply_lighting: bool = Form(True),
    auto_apply_climate: bool = Form(True),
    auto_apply_ventilation: bool = Form(True),
    dry_run: bool = Form(False),
) -> JSONResponse:
    """Bulk apply discovered devices to manifest."""
    if _discovery_service is None or _manifest_path is None:
        raise HTTPException(status_code=503, detail="Discovery service not initialized")

    try:
        from src.core.discovery.models import BulkApplyRequest

        request_model = BulkApplyRequest(
            include_all=include_all,
            auto_apply_lighting=auto_apply_lighting,
            auto_apply_climate=auto_apply_climate,
            auto_apply_ventilation=auto_apply_ventilation,
            dry_run=dry_run,
        )

        result = await _discovery_service.bulk_apply(request_model, _manifest_path)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Bulk apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/discovery/apply-selective")
async def apply_selective(request: Request) -> JSONResponse:
    """Apply selectively chosen devices to manifest.

    Expects JSON body with list of device selections.
    """
    if _discovery_service is None or _manifest_path is None:
        raise HTTPException(status_code=503, detail="Discovery service not initialized")

    try:
        body = await request.json()
        selections = body.get("selections", [])
        dry_run = body.get("dry_run", False)

        result = await _discovery_service.apply_selective(
            selections=selections,
            manifest_path=_manifest_path,
            dry_run=dry_run,
        )
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Selective apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/rooms")
async def get_rooms() -> JSONResponse:
    """Get list of existing rooms from manifest."""
    if _manifest_path is None:
        raise HTTPException(status_code=503, detail="Manifest path not initialized")

    try:
        if _manifest_store is None:
            return JSONResponse(content={"rooms": []})
        if _manifest_store.current is None:
            _manifest_store.load()

        rooms = [{"id": room.id, "name": room.name} for room in _manifest_store.current.rooms]
        return JSONResponse(content={"rooms": rooms})
    except Exception as e:
        logger.error(f"Failed to get rooms: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/discovery/stats")
async def get_stats() -> JSONResponse:
    """Get quick statistics about discovered devices."""
    if _discovery_service is None:
        raise HTTPException(status_code=503, detail="Discovery service not initialized")

    try:
        result = await _discovery_service.scan_devices(page=1, page_size=1)
        return JSONResponse(
            content={
                "total": result["total"],
                "by_domain": result["by_domain"],
                "by_category": result["by_category"],
                "auto_apply_stats": result["auto_apply_stats"],
            }
        )
    except Exception as e:
        logger.error(f"Stats fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
