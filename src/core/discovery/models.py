"""Pydantic models for device discovery."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DeviceCategory(StrEnum):
    """Категории устройств для FSM."""

    LIGHTING = "lighting"
    SWITCH_CONTROL = "switch_control"
    TEMPERATURE_SENSOR = "temperature_sensor"
    HUMIDITY_SENSOR = "humidity_sensor"
    MOTION_SENSOR = "motion_sensor"
    CLIMATE_CONTROL = "climate_control"
    VENTILATION = "ventilation"
    COVER_CONTROL = "cover_control"
    MONITORING_ONLY = "monitoring_only"


class BehaviorTemplate(StrEnum):
    """Существующие шаблоны платформы."""

    LIGHTING = "lighting"
    NIGHT_LIGHT = "night_light"
    CLIMATE_CONTROL = "climate_control"
    HUMIDITY_VENTILATION = "humidity_ventilation"


class DiscoveredDevice(BaseModel):
    """Обнаруженное устройство из Home Assistant."""

    entity_id: str
    domain: str
    name: str
    friendly_name: str | None = None
    area_id: str | None = None
    area_name: str | None = None
    state: str = "unknown"
    attributes: dict[str, Any] = Field(default_factory=dict)
    category: DeviceCategory = DeviceCategory.MONITORING_ONLY
    suggested_behavior: str | None = None
    auto_apply: bool = False  # Применить автоматически без подтверждения


class DeviceScanResult(BaseModel):
    """Результат сканирования."""

    scan_id: str
    scanned_at: datetime = Field(default_factory=datetime.now)
    total_devices: int
    devices: list[DiscoveredDevice] = Field(default_factory=list)
    by_domain: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_area: dict[str, int] = Field(default_factory=dict)


class DeviceSelection(BaseModel):
    """Выбор пользователя."""

    device_entity_id: str
    include: bool = True
    target_room: str
    target_room_name: str | None = None
    behavior_template: str | None = None
    behavior_params: dict[str, Any] = Field(default_factory=dict)


class BulkApplyRequest(BaseModel):
    """Массовое применение (для 200+ устройств)."""

    include_all: bool = False
    include_categories: list[DeviceCategory] = Field(default_factory=list)
    exclude_entities: list[str] = Field(default_factory=list)
    auto_apply_lighting: bool = True
    auto_apply_climate: bool = True
    auto_apply_ventilation: bool = True
    dry_run: bool = False
