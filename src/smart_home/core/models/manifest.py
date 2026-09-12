"""Manifest models for smart home configuration."""

from pathlib import Path
from typing import Annotated, List, Union, Literal

import yaml
from pydantic import BaseModel, Field


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
    schedule: str | None = None


class ClimateHysteresisDevice(DeviceBase):
    """Климатическое устройство с гистерезисом."""

    type: Literal["climate_hysteresis"]
    sensor: str
    target: float
    hysteresis: float
    modes: List[str]


class VentilationHumidityDevice(DeviceBase):
    """Вентиляция с управлением по влажности."""

    type: Literal["ventilation_humidity"]
    humidity_sensor: str
    humidity_threshold: int
    timeout_sec: int


# Полиморфный тип с дискриминатором
AnyDevice = Annotated[
    Union[LightMotionDevice, ClimateHysteresisDevice, VentilationHumidityDevice],
    Field(discriminator="type"),
]


class AutomationRules(BaseModel):
    """Правила автоматизации."""

    lighting: dict | None = None
    climate: dict | None = None
    ventilation: dict | None = None


class DashboardConfig(BaseModel):
    """Конфигурация дашборда."""

    title: str
    show_history: bool = True
    show_climate: bool = True
    show_motion_sensors: bool = True
    history_days: int = 7


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
    devices: List[AnyDevice]
    zones: List[Zone] | None = None
    automation_rules: AutomationRules | None = None
    dashboard: DashboardConfig | None = None


def load_manifest(path: str) -> Manifest:
    """Загружает и валидирует YAML манифест.

    Args:
        path: Путь к YAML файлу манифеста.

    Returns:
        Валидированный объект Manifest.

    Raises:
        FileNotFoundError: Если файл не найден.
        yaml.YAMLError: Если YAML некорректен.
        pydantic.ValidationError: Если данные не проходят валидацию.
    """
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Преобразуем структуру из словаря категорий в плоский список
    if "devices" in data and isinstance(data["devices"], dict):
        devices_list = []
        for category, devices in data["devices"].items():
            if devices is None:
                continue
            for device in devices:
                # Определяем тип устройства по категории и полям
                if category == "lighting":
                    device["type"] = "light_motion"
                elif category == "climate":
                    device["type"] = "climate_hysteresis"
                elif category == "ventilation":
                    device["type"] = "ventilation_humidity"
                devices_list.append(device)
        data["devices"] = devices_list

    return Manifest.model_validate(data)
