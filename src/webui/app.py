"""FastAPI application factory for Web UI."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from loguru import logger

from .models import ManifestModel


if TYPE_CHECKING:
    from src.core.container import Container


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


def create_app(
    manifest_path: str | None = None, container_instance: Container | None = None
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        manifest_path: Path to the manifest file to edit.
                      If None, uses default instance path.
        container_instance: Optional shared Container instance from main.py.
                           If provided, uses its adapter for discovery routes.

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

    # Include discovery routes
    from .routes_discovery import router as discovery_router

    app.include_router(discovery_router)

    # Default manifest path - resolve relative to project root
    if manifest_path is None:
        manifest_path = str(_get_project_root() / "instances" / "leonids_house" / "manifest.yaml")

    # Initialize manifest store
    manifest_store = ManifestStore(manifest_path)

    # Initialize discovery routes with the shared adapter instance
    # The adapter is already connected in main.py via ctx.adapter.start()
    try:
        from src.core.container import Container

        from .routes_discovery import init_discovery_routes

        # Use provided container or create a new one
        if container_instance is not None:
            _container = container_instance
            logger.info("Using shared container instance for discovery routes")
        else:
            _container = Container(manifest_path=manifest_path)
            _ = _container.build()  # Trigger initialization
            logger.info("Created new container instance for discovery routes")

        init_discovery_routes(_container.adapter, manifest_path)
        logger.info("Discovery routes initialized with shared adapter")
    except Exception as e:
        logger.warning(f"Could not initialize discovery routes: {e}")

    # WebSocket connection manager for real-time updates
    class ConnectionManager:
        """Manages WebSocket connections for live updates."""

        def __init__(self) -> None:
            """Initialize the connection manager."""
            self.active_connections: list[WebSocket] = []

        async def connect(self, websocket: WebSocket) -> None:
            """Accept a new WebSocket connection."""
            await websocket.accept()
            self.active_connections.append(websocket)
            logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

        def disconnect(self, websocket: WebSocket) -> None:
            """Remove a WebSocket connection."""
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            logger.info(
                f"WebSocket disconnected. Total connections: {len(self.active_connections)}"
            )

        async def broadcast(self, message: dict) -> None:
            """Send a message to all connected clients."""
            import json

            for connection in self.active_connections:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"Failed to send message to WebSocket: {e}")

    manager = ConnectionManager()

    @app.websocket("/ws/live")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time event streaming."""
        await manager.connect(websocket)
        try:
            while True:
                # Keep connection alive, receive messages if needed
                data = await websocket.receive_text()
                # Optionally handle incoming messages from client
                logger.debug(f"Received WebSocket message: {data}")
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            manager.disconnect(websocket)

    async def broadcast_event(event_data: dict) -> None:
        """Broadcast an event to all connected WebSocket clients."""
        await manager.broadcast(event_data)

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
    async def reload_manifest(request: Request) -> Response:
        """Reload manifest from file (revert unsaved changes).

        Args:
            request: FastAPI request object.

        Returns:
            Redirect to index page or error template.
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

    @app.get("/devices/{room_id}/{device_id}/edit", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def edit_device(request: Request, room_id: int, device_id: str) -> HTMLResponse:
        """Edit a specific device.

        Args:
            request: FastAPI request object.
            room_id: Index of the room containing the device.
            device_id: ID of the device to edit.

        Returns:
            HTML fragment with device edit form.
        """
        try:
            manifest_data = _load_manifest(manifest_path)
            if room_id >= len(manifest_data.get("rooms", [])):
                raise HTTPException(status_code=404, detail="Room not found")

            room = manifest_data["rooms"][room_id]
            device = None
            device_index = -1
            for idx, dev in enumerate(room.get("devices", [])):
                if dev.get("id") == device_id:
                    device = dev
                    device_index = idx
                    break

            if device is None:
                raise HTTPException(status_code=404, detail="Device not found")

            return templates.TemplateResponse(
                request,
                "partials/device_form.html",
                {
                    "device": device,
                    "device_index": device_index,
                    "room_index": room_id,
                },
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to load device: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.get("/devices/{room_id}/add", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def add_device(request: Request, room_id: int) -> HTMLResponse:
        """Add a new device form.

        Args:
            request: FastAPI request object.
            room_id: Index of the room to add device to.

        Returns:
            HTML fragment with empty device form.
        """
        return templates.TemplateResponse(
            request,
            "partials/device_form.html",
            {"device": {}, "device_index": -1, "room_index": room_id},
        )

    @app.post("/devices/save", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def save_device(
        request: Request,
        room_index: str = Form(...),
        device_index: str = Form(...),
        device_id: str = Form(...),
        device_type: str = Form(...),
        device_name: str = Form(""),
    ) -> HTMLResponse:
        """Save device changes.

        Args:
            request: FastAPI request object.
            room_index: Index of the room.
            device_index: Index of the device (-1 for new).
            device_id: Device entity ID.
            device_type: Device type.
            device_name: Human-readable device name.

        Returns:
            HTML response with success/error message.
        """
        import json

        try:
            manifest_data = _load_manifest(manifest_path)
            room_idx = int(room_index)
            dev_idx = int(device_index)

            if room_idx >= len(manifest_data.get("rooms", [])):
                raise HTTPException(status_code=404, detail="Room not found")

            # Build behaviors from form data
            behaviors = []
            form_data = await request.form()
            idx = 0
            while True:
                template_key = f"behavior_template_{idx}"
                if template_key not in form_data:
                    break
                behavior = {
                    "template": form_data[template_key],
                    "priority": int(form_data[f"behavior_priority_{idx}"]),
                    "params": json.loads(form_data.get(f"behavior_params_{idx}", "{}")),
                }
                behaviors.append(behavior)
                idx += 1

            device = {
                "id": device_id,
                "type": device_type,
                "name": device_name,
                "behaviors": behaviors,
            }

            room = manifest_data["rooms"][room_idx]
            if "devices" not in room:
                room["devices"] = []

            if dev_idx >= 0 and dev_idx < len(room["devices"]):
                room["devices"][dev_idx] = device
            else:
                room["devices"].append(device)

            # Validate
            ManifestModel(**manifest_data)

            # Save
            _save_manifest(manifest_path, manifest_data)

            logger.info(f"Device {device_id} saved successfully")

            # Return updated room card
            room_data = room
            room_card_html = f"""
            <div class="card room-card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h3 class="mb-0">{room_data.get("name", "Unknown")} <small class="text-muted">({room_data.get("id", "")})</small></h3>
                    <span class="badge bg-secondary">{len(room_data.get("devices", []))} devices</span>
                </div>
                <div class="card-body">
                    <h5>🔌 Devices</h5>
                    <p>Device {device_id} saved successfully!</p>
                    <button class="btn btn-sm btn-primary"
                            hx-get="/devices/{room_idx}/{device_id}/edit"
                            hx-target="#device-form-container">
                        Edit
                    </button>
                </div>
            </div>
            """
            return HTMLResponse(content=room_card_html)

        except Exception as e:
            logger.error(f"Failed to save device: {e}")
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
