"""Корневая модель манифеста и конфигурация инстанса."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .devices import DevicesConfig
from .features import FeaturesConfig
from .globals_cfg import GlobalsConfig
from .integrations import IntegrationsConfig, DashboardConfig


class InstanceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    customer: str | None = None
    installed_date: str | None = None
    platform_version: str | None = None
    notes: str | None = None


class InstanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9_]+$", description="Уникальный ID, только snake_case")
    name: str
    timezone: str
    locale: str = "ru-RU"
    version: str = Field(..., description="Версия манифеста для миграций")
    metadata: InstanceMetadata = Field(default_factory=InstanceMetadata)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance: InstanceConfig
    devices: DevicesConfig
    features: FeaturesConfig
    globals: GlobalsConfig
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
