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


class LogStore:
    """In-memory storage for application logs."""

    def __init__(self, max_logs: int = 5000) -> None:
        """Initialize the log store.

        Args:
            max_logs: Maximum number of logs to keep in memory.
        """
        self.logs: list[dict] = []
        self.max_logs = max_logs

    def add(self, level: str, message: str, timestamp: str | None = None) -> None:
        """Add a log entry.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            message: Log message.
            timestamp: ISO format timestamp (auto-generated if not provided).
        """
        import datetime

        if timestamp is None:
            timestamp = datetime.datetime.now(datetime.UTC).isoformat()

        log_entry = {
            "timestamp": timestamp,
            "level": level.upper(),
            "message": message,
        }

        self.logs.insert(0, log_entry)  # Add to beginning for newest first
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[: self.max_logs]

    def get_logs(self, limit: int = 1000) -> list[dict]:
        """Get logs.

        Args:
            limit: Maximum number of logs to return.

        Returns:
            List of log entries.
        """
        return self.logs[:limit]

    def clear(self) -> None:
        """Clear all logs."""
        self.logs = []


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

    # Include device management routes (T051-T057)
    try:
        from .routes.devices import devices, sources, websocket

        app.include_router(devices.router)
        app.include_router(sources.router)
        app.include_router(websocket.router)
        logger.info("Device management routes registered")
    except ImportError as e:
        logger.warning(f"Could not import device routes: {e}")

    # Default manifest path - resolve relative to project root
    if manifest_path is None:
        manifest_path = str(_get_project_root() / "instances" / "leonids_house" / "manifest.yaml")

    # Initialize manifest store
    manifest_store = ManifestStore(manifest_path)

    # Initialize log store
    log_store = LogStore()

    # Add initial info log
    log_store.add("INFO", "Web UI started")

    # Configure loguru to log to both console and log store
    def loguru_sink(message):
        """Custom loguru sink to write logs to log store."""
        try:
            # Extract log level and message from loguru record
            record = message.record
            level = record["level"].name
            msg = record["message"]
            timestamp = record["time"].isoformat()
            log_store.add(level, msg, timestamp)
        except Exception:
            pass  # Silently ignore logging errors to avoid recursion

    # Remove default handlers and add custom ones
    logger.remove()
    logger.add(loguru_sink, format="{message}", level="DEBUG")
    # Keep console logging for development
    logger.add(
        lambda msg: print(msg, end=""),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
    )
    # The adapter is already connected in main.py via ctx.adapter.start()
    _container = None
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

        init_discovery_routes(_container.adapter, manifest_path, container=_container)
        logger.info("Discovery routes initialized with shared adapter")
    except Exception as e:
        logger.warning(f"Could not initialize discovery routes: {e}")

    # Expose the platform container to routers that need it (e.g. FSM diagrams)
    app.state.container = _container

    # Initialize device management services (T049-T060)
    try:
        from src.core.events.event_bus import EventBus
        from src.services.device_service import DeviceService

        event_bus = EventBus()
        persistence = None

        try:
            from src.core.persistence.manager import PersistenceManager
            persistence = PersistenceManager(data_dir="data")
        except ImportError as e:
            logger.warning(f"Could not initialize PersistenceManager: {e}. Running with limited functionality.")

        device_service = DeviceService(
            event_bus=event_bus,
            persistence_module=persistence,
            ha_adapter=None,  # TODO: Connect HA adapter
        )

        app.state.event_bus = event_bus
        app.state.persistence = persistence
        app.state.device_service = device_service
        logger.info("Device management services initialized")
    except Exception as e:
        logger.warning(f"Could not initialize device services: {e}")

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
            # Ensure manifest is loaded
            if manifest_store.current is None:
                manifest_store.load()

            if room_id >= len(manifest_store.current.rooms):
                raise HTTPException(status_code=404, detail="Room not found")

            room = manifest_store.current.rooms[room_id]
            device = None
            device_index = -1
            for idx, dev in enumerate(room.devices):
                if dev.id == device_id:
                    device = dev
                    device_index = idx
                    break

            if device is None:
                raise HTTPException(status_code=404, detail="Device not found")

            # Load available templates
            from .template_loader import get_template_loader

            loader = get_template_loader()
            templates_data = loader.load_all()
            template_list = sorted(templates_data.keys())

            return templates.TemplateResponse(
                request,
                "partials/device_form.html",
                {
                    "device": device,
                    "device_index": device_index,
                    "room_index": room_id,
                    "current_room_id": room.id,
                    "available_rooms": manifest_store.current.rooms,
                    "available_templates": template_list,
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
        try:
            # Ensure manifest is loaded
            if manifest_store.current is None:
                manifest_store.load()

            # Load available templates
            from .template_loader import get_template_loader

            loader = get_template_loader()
            templates_data = loader.load_all()
            template_list = sorted(templates_data.keys())

            # Get room info
            rooms = manifest_store.current.rooms if manifest_store.current else []
            current_room_id = rooms[room_id].id if room_id < len(rooms) else ""

            return templates.TemplateResponse(
                request,
                "partials/device_form.html",
                {
                    "device": {},
                    "device_index": -1,
                    "room_index": room_id,
                    "current_room_id": current_room_id,
                    "available_rooms": rooms,
                    "available_templates": template_list,
                },
            )
        except Exception as e:
            logger.error(f"Failed to load add device form: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

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
            from .models import BehaviorConfig, DeviceConfig

            # Ensure manifest is loaded
            if manifest_store.current is None:
                manifest_store.load()

            room_idx = int(room_index)
            dev_idx = int(device_index)

            if room_idx >= len(manifest_store.current.rooms):
                raise HTTPException(status_code=404, detail="Room not found")

            # Save backup for undo
            manifest_store.backup = copy.deepcopy(manifest_store.current)

            # Build behaviors from form data
            behaviors = []
            form_data = await request.form()
            idx = 0
            while True:
                template_key = f"behavior_template_{idx}"
                if template_key not in form_data:
                    break
                behavior = BehaviorConfig(
                    template=form_data[template_key],
                    priority=int(form_data[f"behavior_priority_{idx}"]),
                    params=json.loads(form_data.get(f"behavior_params_{idx}", "{}")),
                )
                behaviors.append(behavior)
                idx += 1

            device = DeviceConfig(
                id=device_id,
                type=device_type,
                name=device_name,
                behaviors=behaviors,
            )

            # Check if room was changed (move device to different room)
            target_room_id = form_data.get("room_id", "")
            current_room = manifest_store.current.rooms[room_idx]

            # Find target room by ID if specified
            target_room = current_room
            target_room_idx = room_idx

            if target_room_id and target_room_id != current_room.id:
                # Find room by ID
                for idx, room in enumerate(manifest_store.current.rooms):
                    if room.id == target_room_id:
                        target_room = room
                        target_room_idx = idx
                        break

                logger.info(
                    f"Moving device {device_id} from room {current_room.id} to {target_room.id}"
                )

            # Remove device from current room if it exists and room changed
            if dev_idx >= 0 and dev_idx < len(current_room.devices) and target_room_idx != room_idx:
                current_room.devices.pop(dev_idx)

            # Add/update device in target room
            if dev_idx >= 0 and dev_idx < len(target_room.devices) and target_room_idx == room_idx:
                # Update existing device in same room
                target_room.devices[dev_idx] = device
            else:
                # Add new device or to different room
                target_room.devices.append(device)

            manifest_store.mark_changed()
            # Persist changes to YAML file with backup
            manifest_store.save()
            logger.info(f"Device {device_id} saved successfully")

            # Return success response that closes modal and reloads page
            return templates.TemplateResponse(
                request,
                "partials/save_success.html",
                {"message": f"Device {device_id} saved successfully!"},
            )

        except Exception as e:
            logger.error(f"Failed to save device: {e}")
            return templates.TemplateResponse(
                request,
                "partials/save_error.html",
                {"error": str(e)},
                status_code=400,
            )

    @app.get("/logs", response_class=HTMLResponse)  # type: ignore[untyped-decorator]
    async def logs_page(request: Request) -> HTMLResponse:
        """Render the logs page.

        Args:
            request: FastAPI request object.

        Returns:
            HTML response with logs viewer.
        """
        return templates.TemplateResponse(request, "logs.html", {})

    @app.get("/api/logs")  # type: ignore[untyped-decorator]
    async def get_logs(limit: int = 1000) -> list:
        """Get application logs.

        Args:
            limit: Maximum number of logs to return.

        Returns:
            List of log entries.
        """
        return log_store.get_logs(limit)

    @app.delete("/api/logs")  # type: ignore[untyped-decorator]
    async def clear_logs() -> dict:
        """Clear all logs.

        Returns:
            Status message.
        """
        log_store.clear()
        logger.info("Logs cleared via API")
        return {"status": "success", "message": "Logs cleared"}

    @app.websocket("/ws/logs")  # type: ignore[untyped-decorator]
    async def websocket_logs(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time log streaming.

        Args:
            websocket: WebSocket connection.
        """
        await websocket.accept()
        try:
            while True:
                # Keep connection alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass

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
