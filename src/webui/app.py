"""FastAPI application factory for Web UI."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from .models import ManifestModel


if TYPE_CHECKING:
    pass


class ManifestStore:
    """In-memory storage for manifest with undo support."""

    def __init__(self, path: str) -> None:
        """Initialize the manifest store.

        Args:
            path: Path to the manifest YAML file.
        """
        self.path = path
        self.current: ManifestModel | None = None
        self.backup: ManifestModel | None = None
        self.has_unsaved_changes: bool = False

    def load(self) -> ManifestModel:
        """Load manifest from YAML file.

        Returns:
            Loaded and validated manifest model.

        Raises:
            FileNotFoundError: If manifest file doesn't exist.
            ValidationError: If manifest is invalid.
        """
        with open(self.path) as f:
            data = yaml.safe_load(f) or {}

        self.current = ManifestModel(**data)
        self.backup = None
        self.has_unsaved_changes = False
        logger.info(f"Manifest loaded from {self.path}")
        return self.current

    def save(self) -> None:
        """Save current manifest to YAML file with backup.

        Creates a timestamped backup before saving.

        Raises:
            ValueError: If no manifest is loaded.
        """
        if self.current is None:
            raise ValueError("No manifest loaded")

        # Create backup
        backup_path = f"{self.path}.bak"
        with open(backup_path, "w") as f:
            if self.backup:
                yaml.dump(self.backup.model_dump(), f, default_flow_style=False, sort_keys=False)
            else:
                # No previous backup, save current as backup
                yaml.dump(self.current.model_dump(), f, default_flow_style=False, sort_keys=False)

        # Save current
        with open(self.path, "w") as f:
            yaml.dump(self.current.model_dump(), f, default_flow_style=False, sort_keys=False)

        self.backup = copy.deepcopy(self.current)
        self.has_unsaved_changes = False
        logger.info(f"Manifest saved to {self.path}, backup at {backup_path}")

    def revert(self) -> ManifestModel:
        """Revert to last saved state (undo).

        Returns:
            Reverted manifest model.

        Raises:
            ValueError: If no manifest is loaded.
        """
        if self.current is None:
            raise ValueError("No manifest loaded")

        if self.backup is not None:
            self.current = copy.deepcopy(self.backup)
        else:
            # Reload from file
            self.load()

        self.has_unsaved_changes = False
        logger.info("Manifest reverted to last saved state")
        return self.current

    def mark_changed(self) -> None:
        """Mark the manifest as having unsaved changes."""
        self.has_unsaved_changes = True


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

    # Initialize manifest store
    manifest_store = ManifestStore(manifest_path)

    @app.get("/", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def index(request: Request) -> HTMLResponse:
        """Render the main manifest editor page.

        Args:
            request: FastAPI request object.

        Returns:
            HTML response with the manifest editor form.
        """
        try:
            manifest_store.load()
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")
            manifest_store.current = ManifestModel(
                instance={
                    "id": "error",
                    "name": "Error loading",
                    "owner": "unknown",
                    "created_at": "",
                },
                version=1,
                rooms=[],
            )

        # Calculate stats
        total_devices = sum(len(room.devices) for room in manifest_store.current.rooms)
        total_behaviors = sum(
            len(device.behaviors)
            for room in manifest_store.current.rooms
            for device in room.devices
        )

        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "manifest": manifest_store.current,
                "has_unsaved_changes": manifest_store.has_unsaved_changes,
                "total_devices": total_devices,
                "total_behaviors": total_behaviors,
            },
        )

    @app.post("/save", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def save_manifest(
        request: Request,
    ) -> HTMLResponse:
        """Save the edited manifest to YAML file.

        Args:
            request: FastAPI request object.

        Returns:
            HTML response with success/error message.
        """
        try:
            manifest_store.save()
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

    @app.get("/manifest/reload")  # type: ignore[untyped-decorator]
    async def reload_manifest(request: Request) -> RedirectResponse:
        """Reload manifest from file (revert unsaved changes).

        Args:
            request: FastAPI request object.

        Returns:
            Redirect to index page.
        """
        try:
            manifest_store.revert()
        except Exception as e:
            logger.error(f"Failed to reload manifest: {e}")
            return templates.TemplateResponse(
                request,
                "partials/save_error.html",
                {"error": str(e)},
                status_code=400,
            )

        # Redirect to index
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/")

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
            if manifest_store.current is None or room_id >= len(manifest_store.current.rooms):
                raise HTTPException(status_code=404, detail="Room not found")

            room = manifest_store.current.rooms[room_id]
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
    async def add_room(
        request: Request,
        room_id: str = Form(...),
        room_name: str = Form(...),
    ) -> HTMLResponse:
        """Add a new room to the manifest.

        Args:
            request: FastAPI request object.
            room_id: Room identifier.
            room_name: Human-readable room name.

        Returns:
            HTML fragment with updated room list or error message.
        """
        try:
            if manifest_store.current is None:
                raise HTTPException(status_code=500, detail="No manifest loaded")

            # Save backup for undo
            manifest_store.backup = copy.deepcopy(manifest_store.current)

            # Create new room
            from .models import RoomConfig

            new_room = RoomConfig(id=room_id, name=room_name, sensors={}, devices=[])
            manifest_store.current.rooms.append(new_room)
            manifest_store.mark_changed()

            # Return updated room card
            return templates.TemplateResponse(
                request,
                "partials/room_card.html",
                {"room": new_room, "room_index": len(manifest_store.current.rooms) - 1},
            )
        except Exception as e:
            logger.error(f"Failed to add room: {e}")
            return templates.TemplateResponse(
                request,
                "partials/save_error.html",
                {"error": str(e)},
                status_code=400,
            )

    @app.post("/rooms/{room_id}/update", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def update_room(
        request: Request,
        room_id: int,
        name: str = Form(...),
    ) -> HTMLResponse:
        """Update an existing room.

        Args:
            request: FastAPI request object.
            room_id: Index of the room to update.
            name: New room name.

        Returns:
            HTML fragment with updated room card.
        """
        try:
            if manifest_store.current is None or room_id >= len(manifest_store.current.rooms):
                raise HTTPException(status_code=404, detail="Room not found")

            # Save backup for undo
            manifest_store.backup = copy.deepcopy(manifest_store.current)

            # Update room
            room = manifest_store.current.rooms[room_id]
            room.name = name
            manifest_store.mark_changed()

            # Return updated room card
            return templates.TemplateResponse(
                request,
                "partials/room_card.html",
                {"room": room, "room_index": room_id},
            )
        except Exception as e:
            logger.error(f"Failed to update room: {e}")
            return templates.TemplateResponse(
                request,
                "partials/save_error.html",
                {"error": str(e)},
                status_code=400,
            )

    @app.delete("/rooms/{room_id}", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def delete_room(request: Request, room_id: int) -> HTMLResponse:
        """Delete a room from the manifest.

        Args:
            request: FastAPI request object.
            room_id: Index of the room to delete.

        Returns:
            Empty HTML fragment (room removed).
        """
        try:
            if manifest_store.current is None or room_id >= len(manifest_store.current.rooms):
                raise HTTPException(status_code=404, detail="Room not found")

            # Save backup for undo
            manifest_store.backup = copy.deepcopy(manifest_store.current)

            # Delete room
            manifest_store.current.rooms.pop(room_id)
            manifest_store.mark_changed()

            # Return empty content
            return HTMLResponse(content="")
        except Exception as e:
            logger.error(f"Failed to delete room: {e}")
            return templates.TemplateResponse(
                request,
                "partials/save_error.html",
                {"error": str(e)},
                status_code=400,
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
