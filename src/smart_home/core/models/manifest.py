"""Pydantic v2 models for smart home manifest."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, Field


class BehaviorConfig(BaseModel):
    """Конфигурация поведения устройства.
    
    Attributes:
        template: Имя YAML-файла шаблона из features/.
        priority: Приоритет поведения (чем меньше число, тем выше приоритет).
        params: Опциональные параметры для настройки поведения.
    """
    template: str = Field(..., description="Имя YAML-файла шаблона из features/")
    priority: int = Field(..., ge=0, description="Приоритет поведения (меньше = выше приоритет)")
    params: dict[str, Any] = Field(default_factory=dict, description="Опциональные параметры поведения")


class DeviceBase(BaseModel):
    """Базовый класс для всех устройств."""

    id: str
    name: str
    room: str
    behaviors: list[BehaviorConfig] = Field(default_factory=list, description="Список поведений устройства")


class LightMotionDevice(DeviceBase):
    """Устройство освещения с датчиком движения."""

    type: Literal["light_motion"]


class ClimateHysteresisDevice(DeviceBase):
    """Климатическое устройство с гистерезисом."""

    type: Literal["climate_hysteresis"]


class VentilationHumidityDevice(DeviceBase):
    """Вентиляционное устройство с контролем влажности."""

    type: Literal["ventilation_humidity"]


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
    global_manual_lockout_min: int = Field(
        default=0,
        description="Глобальное время блокировки автоматизации после ручного управления (минуты). 0 = отключено"
    )


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
    from pydantic import ValidationError

    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    try:
        return Manifest.model_validate(data)
    except ValidationError as e:
        print("\n=== Ошибка валидации манифеста ===", file=sys.stderr)
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error.get("loc", []))
            msg = error.get("msg", "")
            error_type = error.get("type", "")
            print(f"  Поле: {loc}", file=sys.stderr)
            print(f"  Тип ошибки: {error_type}", file=sys.stderr)
            print(f"  Сообщение: {msg}", file=sys.stderr)
            print("-" * 40, file=sys.stderr)
        raise
