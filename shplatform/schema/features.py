"""Модели фич. Ссылаются на устройства ТОЛЬКО по id (через *_ref)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True


class LightingZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    device_refs: list[str] = Field(default_factory=list)
    schedule_calendar: str | None = None
    overrides: list[str] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)


class Lighting(FeatureBase):
    zones: list[LightingZone] = Field(default_factory=list)


class IrrigationZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    valve_ref: str | None = None
    schedule_calendar: str | None = None
    moisture_sensor_ref: str | None = None
    overrides: list[str] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)


class Irrigation(FeatureBase):
    zones: list[IrrigationZone] = Field(default_factory=list)


class ClimateActuatorRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    ref: str
    role: str
    priority: int

class ClimateSeason(BaseModel):
    """Сезонность от внешнего флага (напр. input_boolean.zima)."""
    model_config = ConfigDict(extra="allow")
    source: str | None = None        # entity_id флага сезона
    heating_when: str = "on"         # значение флага = сезон нагрева


class ClimateGlobalSafety(BaseModel):
    """Глобальные предохранители климата."""
    model_config = ConfigDict(extra="allow")
    min_setpoint: float | None = None   # аварийный минимум, ниже не опускаемся

class ClimateSafety(BaseModel):
    model_config = ConfigDict(extra="allow")
    floor_max_temp_ref: str | None = None
    floor_max_temp: float | None = None
    sensor_unavailable_timeout_min: int = 5
    emergency_off_on_sensor_loss: bool = True


class ClimateZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    temp_sensor_ref: str | None = None
    setpoints: dict = Field(default_factory=dict)
    actuators: list[ClimateActuatorRef] = Field(default_factory=list)
    safety: ClimateSafety | None = None


class SeasonDetection(BaseModel):
    model_config = ConfigDict(extra="allow")
    mode: str = "auto"
    heating_threshold: float = 15
    cooling_threshold: float = 20
    hysteresis_hours: int = 24


class Climate(FeatureBase):
    mode: str = "real"                 # shadow | real
    season_detection: SeasonDetection = Field(default_factory=SeasonDetection)
    season: ClimateSeason | None = None
    safety: ClimateGlobalSafety | None = None
    zones: list[ClimateZone] = Field(default_factory=list)


# ============================================================
# SENSOR HEALTH
# ============================================================
class SensorHealthSensor(BaseModel):
    model_config = ConfigDict(extra="allow")
    entity: str
    battery: str | None = None
    count: int = 1


class SensorHealth(FeatureBase):
    check_interval_min: int = 10
    battery_threshold: int = 20
    sensors: list[SensorHealthSensor] = Field(default_factory=list)


# ============================================================
# VENTILATION
# ============================================================
class VentilationDevice(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    entity: str


class VentilationRoom(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    temp: str | None = None


class VentilationOpenDoorsSensor(BaseModel):
    model_config = ConfigDict(extra="allow")
    entity: str


class VentilationOpenDoors(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled_flag: str | None = None
    mock: bool = False
    mock_state: str | None = None
    sensors: list[VentilationOpenDoorsSensor] = Field(default_factory=list)


class VentilationBathroomFan(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled_flag: str | None = None
    entity: str
    temp_sensor: str | None = None
    humidity_sensor: str | None = None
    temp_min: float = 26
    humidity_min: float = 60
    run_minutes: int = 15


class Ventilation(FeatureBase):
    mode: str = "real"
    override_timeout_min: int = 60
    devices: list[VentilationDevice] = Field(default_factory=list)
    sensors: dict = Field(default_factory=dict)
    rooms: list[VentilationRoom] = Field(default_factory=list)
    setpoints_ref: dict = Field(default_factory=dict)
    speeds: dict = Field(default_factory=dict)
    deltas: dict = Field(default_factory=dict)
    boost_minutes: int = 60
    winter_pause_outdoor_max: float | None = None
    flags: dict = Field(default_factory=dict)
    open_doors: VentilationOpenDoors | None = None
    bathroom_fan: VentilationBathroomFan | None = None


# ============================================================
# FEATURES CONFIG
# ============================================================
class FeaturesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lighting: Lighting = Field(default_factory=Lighting)
    irrigation: Irrigation = Field(default_factory=Irrigation)
    climate: Climate = Field(default_factory=Climate)
    sensor_health: SensorHealth = Field(default_factory=SensorHealth)
    ventilation: Ventilation = Field(default_factory=Ventilation)
    security: FeatureBase = Field(default_factory=lambda: FeatureBase(enabled=False))
    energy: FeatureBase = Field(default_factory=lambda: FeatureBase(enabled=False))
