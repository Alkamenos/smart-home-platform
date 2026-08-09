"""Модели устройств. Все entity_id живут ТОЛЬКО здесь."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeviceBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(..., pattern=r"^[a-z0-9_]+$", description="Логический ID устройства")


class HybridSwitchMode(BaseModel):
    model_config = ConfigDict(extra="allow")
    physical_override: dict | None = None
    button_actions: dict[str, dict] | None = None


class HybridSwitch(DeviceBase):
    adapter: str = Field(..., description="Имя адаптера, напр. z2m_aqara_h1m")
    relay_entity: str
    button_event_sensor: str | None = None
    initial_mode: str = "control_relay"
    modes: dict[str, HybridSwitchMode] = Field(default_factory=dict)
    auto_mode_switch: list[dict] = Field(default_factory=list)


class Light(DeviceBase):
    entity: str
    type: str = "zigbee_switch"


class Sensor(DeviceBase):
    entity: str
    role: str | None = None


class Actuator(DeviceBase):
    entity: str
    type: str = Field(..., description="relay | climate_device | recuperator | ...")
    safety_max_temp_entity: str | None = None
    safety_max_temp: float | None = None
    min_cycle_minutes: int | None = None


class Valve(DeviceBase):
    entity: str
    type: str = "zigbee_valve"


class DevicesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hybrid_switches: list[HybridSwitch] = Field(default_factory=list)
    lights: list[Light] = Field(default_factory=list)
    sensors: list[Sensor] = Field(default_factory=list)
    actuators: list[Actuator] = Field(default_factory=list)
    valves: list[Valve] = Field(default_factory=list)

    def all_ids(self) -> set[str]:
        ids: set[str] = set()
        for group in (self.hybrid_switches, self.lights, self.sensors,
                      self.actuators, self.valves):
            ids.update(d.id for d in group)
        return ids

    def by_id(self) -> dict[str, DeviceBase]:
        mapping: dict[str, DeviceBase] = {}
        for group in (self.hybrid_switches, self.lights, self.sensors,
                      self.actuators, self.valves):
            for d in group:
                mapping[d.id] = d
        return mapping
