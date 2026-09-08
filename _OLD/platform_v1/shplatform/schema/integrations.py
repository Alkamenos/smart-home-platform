"""Интеграции и генерация дашборда. Зарезервированы для расширения."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Integration(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False


class IntegrationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yandex_dialogs: Integration = Field(default_factory=Integration)
    telegram_bot: Integration = Field(default_factory=Integration)
    mqtt_broker: Integration = Field(default_factory=Integration)


class DashboardPage(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    sections: list[dict] = Field(default_factory=list)


class DashboardConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    template_engine: str = "jinja2"
    templates_dir: str = "templates/dashboards/"
    pages: list[DashboardPage] = Field(default_factory=list)
