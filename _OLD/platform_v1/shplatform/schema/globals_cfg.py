"""Глобальные режимы и override-политики."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GlobalMode(BaseModel):
    model_config = ConfigDict(extra="allow")
    entity: str
    affects: list[str] = Field(default_factory=list)


class OverridePolicy(BaseModel):
    model_config = ConfigDict(extra="allow")
    priority: str = "lowest"
    duration: str | None = None
    default_timeout_min: int | None = None


class GlobalsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modes: dict[str, GlobalMode] = Field(default_factory=dict)
    override_policy: dict[str, OverridePolicy] = Field(default_factory=dict)
    evaluation_intervals: dict[str, int] = Field(default_factory=dict)
