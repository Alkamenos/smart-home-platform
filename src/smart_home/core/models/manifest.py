"""Pydantic v2 модели для манифеста умного дома с полиморфизмом через discriminator."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError


class DeviceBase(BaseModel):
    """Базовый класс для всех устройств."""

    id: str
    name: str
    room: str


class LightMotionDevice(DeviceBase):
    """Устройство освещения с датчиком движения."""

    type: Literal["light_motion"]
    motion_sensor: str
    motion_timeout_sec: int
    schedule: Optional[str] = None


class ClimateHysteresisDevice(DeviceBase):
    """Климатическое устройство с гистерезисом."""

    type: Literal["climate_hysteresis"]
    sensor: str
    target: float
    hysteresis: float
    modes: List[str]


class VentilationHumidityDevice(DeviceBase):
    """Вентиляция на основе влажности."""

    type: Literal["ventilation_humidity"]
    humidity_sensor: str
    humidity_threshold: int
    timeout_sec: int


AnyDevice = Annotated[
    Union[LightMotionDevice, ClimateHysteresisDevice, VentilationHumidityDevice],
    Field(discriminator="type"),
]


class AutomationRules(BaseModel):
    """Правила автоматизации."""

    lighting: Optional[dict] = None
    climate: Optional[dict] = None
    ventilation: Optional[dict] = None


class Dashboard(BaseModel):
    """Настройки дашборда."""

    title: str
    show_history: bool
    show_climate: bool
    show_motion_sensors: bool
    history_days: int


class InstanceInfo(BaseModel):
    """Информация об экземпляре."""

    id: str
    name: str
    owner: str
    created_at: str


class Zone(BaseModel):
    """Зона дома."""

    id: str
    name: str
    floor: int


class Manifest(BaseModel):
    """Корневая модель манифеста."""

    version: int
    instance: InstanceInfo
    zones: List[Zone]
    devices: List[AnyDevice]
    automation_rules: AutomationRules
    dashboard: Dashboard


def load_manifest(path: str) -> Manifest:
    """Загружает и валидирует YAML манифест.

    Args:
        path: Путь к YAML файлу манифеста.

    Returns:
        Валидированная модель Manifest.

    Raises:
        FileNotFoundError: Если файл не найден.
        ValidationError: Если YAML невалиден (с красивым выводом ошибок).
        yaml.YAMLError: Если YAML синтаксически неверен.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(file_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    try:
        return Manifest.model_validate(raw_data)
    except ValidationError as e:
        error_lines = []
        error_lines.append(f"\n❌ Validation Error in manifest '{path}':")
        error_lines.append("=" * 50)

        for error in e.errors():
            loc = " → ".join(str(x) for x in error.get("loc", []))
            msg = error.get("msg", "Unknown error")
            error_type = error.get("type", "unknown")

            error_lines.append(f"  • Поле: {loc}")
            error_lines.append(f"    Ошибка: {msg}")
            error_lines.append(f"    Тип: {error_type}")
            error_lines.append("-" * 50)

        raise ValueError("\n".join(error_lines)) from e
