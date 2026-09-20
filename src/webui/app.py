"""FastAPI application factory for Web UI."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from src.core.models.manifest import Manifest

from .models import ManifestModel


if TYPE_CHECKING:
    pass


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def create_app(manifest_path: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        manifest_path: Path to the manifest file to edit.
                      If None, uses default instance path.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Smart Home Manifest Editor",
        description="Web UI for editing smart home FSM manifests",
        version="1.0.0",
    )

    # Setup templates
    template_dir = Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(template_dir))

    # Include routes
    from .routes import router

    app.include_router(router)

    # Default manifest path - resolve relative to project root
    if manifest_path is None:
        manifest_path = str(_get_project_root() / "instances" / "leonids_house" / "manifest.yaml")

    @app.get("/", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def index(request: Request) -> HTMLResponse:
        """Render the main manifest editor page.

        Args:
            request: FastAPI request object.

        Returns:
            HTML response with the manifest editor form.
        """
        try:
            manifest_data = _load_manifest(manifest_path)
            validated = ManifestModel(**manifest_data)
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")
            manifest_data = {
                "instance": {
                    "id": "error",
                    "name": "Error loading",
                    "owner": "unknown",
                    "created_at": "",
                },
                "version": 1,
                "rooms": [],
            }
            validated = ManifestModel(**manifest_data)

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "manifest": validated,
                "manifest_json": manifest_data,
            },
        )

    @app.post("/save", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def save_manifest(
        request: Request,
        manifest_data: str = Form(...),
    ) -> HTMLResponse:
        """Save the edited manifest.

        Args:
            request: FastAPI request object.
            manifest_data: JSON string of the manifest data.

        Returns:
            HTML response with success/error message.
        """
        import json

        try:
            data = json.loads(manifest_data)
            ManifestModel(**data)

            # Validate against core Manifest model
            Manifest(**data)

            # Save to file
            _save_manifest(manifest_path, data)

            logger.info(f"Manifest saved successfully to {manifest_path}")

            return templates.TemplateResponse(
                request,
                "partials/save_success.html",
                {"message": "Manifest saved successfully!"},
            )
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")
            return templates.TemplateResponse(
                request,
                "partials/save_error.html",
                {"error": str(e)},
                status_code=400,
            )

    @app.get("/rooms/{room_id}/edit", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def edit_room(request: Request, room_id: int) -> HTMLResponse:
        """Edit a specific room.

        Args:
            request: FastAPI request object.
            room_id: Index of the room to edit.

        Returns:
            HTML fragment with room edit form.
        """
        try:
            manifest_data = _load_manifest(manifest_path)
            if room_id >= len(manifest_data.get("rooms", [])):
                raise HTTPException(status_code=404, detail="Room not found")

            room = manifest_data["rooms"][room_id]
            return templates.TemplateResponse(
                request,
                "partials/room_form.html",
                {"room": room, "room_index": room_id},
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to load room: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/rooms/add", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def add_room(request: Request) -> HTMLResponse:
        """Add a new room form.

        Args:
            request: FastAPI request object.

        Returns:
            HTML fragment with empty room form.
        """
        return templates.TemplateResponse(
            request,
            "partials/room_form.html",
            {"room": {}, "room_index": -1},
        )

    return app


def _load_manifest(path: str) -> dict:
    """Load manifest from YAML file.

    Args:
        path: Path to the manifest file.

    Returns:
        Manifest data as dictionary.
    """
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_manifest(path: str, data: dict) -> None:
    """Save manifest to YAML file.

    Args:
        path: Path to the manifest file.
        data: Manifest data to save.
    """
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
