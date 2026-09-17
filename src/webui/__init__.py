"""Web UI module for manifest editing.

This module provides a FastAPI-based web interface for editing
smart home FSM manifests with HTMX-powered forms.
"""

from .app import create_app
from .models import BehaviorModel, DeviceModel, ManifestModel, RoomModel
from .routes import router


__all__ = [
    "create_app",
    "router",
    "ManifestModel",
    "DeviceModel",
    "BehaviorModel",
    "RoomModel",
]
