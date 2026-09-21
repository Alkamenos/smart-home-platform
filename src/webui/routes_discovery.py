"""Routes for Device Discovery Wizard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger


if TYPE_CHECKING:
    from src.adapters.ha_adapter import HAAdapter

router = APIRouter()

_discovery_service = None
_manifest_path: str | None = None


def init_discovery_routes(ha_adapter: HAAdapter, manifest_path: str) -> None:
    """Initialize the discovery service with HA adapter and manifest path."""
    global _discovery_service, _manifest_path
    from src.core.discovery.discovery_service import DeviceDiscoveryService

    _discovery_service = DeviceDiscoveryService(ha_adapter)
    _manifest_path = manifest_path
    logger.info(f"Discovery routes initialized with manifest: {manifest_path}")


@router.get("/discovery", response_class=HTMLResponse)
async def discovery_page(request: Request) -> HTMLResponse:
    """Render the device discovery wizard page."""
    template_dir = Path(__file__).parent / "templates"
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(template_dir))

    return templates.TemplateResponse(
        request,
        "discovery.html",
        {},
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
