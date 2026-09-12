"""Pydantic v2 models for smart home manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union

import yaml
from pydantic import BaseModel, Field


class DeviceBase(BaseModel):
    """Базовый класс для всех устройств."""

    id: str
    name: str
    room: str


class LightMotionDevice(DeviceBase):
    """Устройство освещения с датчиком движения."""

    type: Literal["light_motion"] = "light_motion"
    motion_sensor: str
    motion_timeout_sec: int
    schedule: str


class ClimateHysteresisDevice(DeviceBase):
    """Климатическое устройство с гистерезисом."""

    type: Literal["climate_hysteresis"] = "climate_hysteresis"
    sensor: str
    target: float
    hysteresis: float
    modes: list[str]


class VentilationHumidityDevice(DeviceBase):
    """Вентиляционное устройство с контролем влажности."""

    type: Literal["ventilation_humidity"] = "ventilation_humidity"
    humidity_sensor: str
    humidity_threshold: int
    timeout_sec: int


AnyDevice = Annotated[
    Union[LightMotionDevice, ClimateHysteresisDevice, VentilationHumidityDevice],
    Field(discriminator="type"),
]


class Zone(BaseModel):
    """Зона в доме."""

    id: str
    name: str
    floor: int


class LightingAutomation(BaseModel):
    """Настройки автоматизации освещения."""

    motion_enabled: bool
    schedule_enabled: bool
    manual_lockout_min: int


class ClimateAutomation(BaseModel):
    """Настройки климатической автоматизации."""

    safety_lockout_enabled: bool
    away_mode_enabled: bool
    manual_lockout_min: int


class VentilationAutomation(BaseModel):
    """Настройки автоматизации вентиляции."""

    humidity_based: bool
    manual_lockout_min: int


class AutomationRules(BaseModel):
    """Правила автоматизации."""

    lighting: LightingAutomation
    climate: ClimateAutomation
    ventilation: VentilationAutomation


class Dashboard(BaseModel):
    """Настройки дашборда."""

    title: str
    show_history: bool
    show_climate: bool
    show_motion_sensors: bool
    history_days: int


class InstanceInfo(BaseModel):
    """Информация об инстансе."""

    id: str
    name: str
    owner: str
    created_at: str


class Manifest(BaseModel):
    """Корневая модель манифеста умного дома."""

    version: int
    instance: InstanceInfo
    zones: list[Zone]
    devices: list[AnyDevice]
    automation_rules: AutomationRules
    dashboard: Dashboard


def load_manifest(path: str) -> Manifest:
    """
    Загрузить и валидировать YAML манифест.

    Args:
        path: Путь к YAML файлу манифеста.

    Returns:
        Manifest: Валидированная модель манифеста.

    Raises:
        FileNotFoundError: Если файл не найден.
        yaml.YAMLError: При ошибке парсинга YAML.
        pydantic.ValidationError: При ошибке валидации данных.
    """
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return Manifest.model_validate(data)
