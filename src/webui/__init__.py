"""Web UI module for manifest editing.

This module provides a FastAPI-based web interface for editing
smart home FSM manifests with HTMX-powered forms.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from .app import create_app
from .models import BehaviorConfig, DeviceConfig, ManifestModel, RoomConfig
from .routes import router


__all__ = [
    "create_app",
    "router",
    "ManifestModel",
    "DeviceConfig",
    "BehaviorConfig",
    "RoomConfig",
]
