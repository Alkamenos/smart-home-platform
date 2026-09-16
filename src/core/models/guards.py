"""Pydantic models for declarative guards DSL."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TimeGuardConfig(BaseModel):
    """Configuration for time-based guard.
    
    Attributes:
        type: Guard type identifier ("time").
        between: Time range in "HH:MM-HH:MM" format.
    """
    
    type: Literal["time"] = "time"
    between: str
    
    @field_validator("between")
    @classmethod
    def validate_time_range(cls, v: str) -> str:
        """Validate time range format."""
        from datetime import datetime
        
        if "-" not in v:
            raise ValueError("Time range must be in 'HH:MM-HH:MM' format")
        
        parts = v.split("-")
        if len(parts) != 2:
            raise ValueError("Time range must have exactly start and end times")
        
        for part in parts:
            try:
                datetime.strptime(part.strip(), "%H:%M")
            except ValueError:
                raise ValueError(f"Invalid time format: {part}. Expected HH:MM")
        
        return v


class StateGuardConfig(BaseModel):
    """Configuration for state-based guard.
    
    Attributes:
        type: Guard type identifier ("state").
        entity: Entity ID to check (e.g., "binary_sensor.alarm").
        is_state: Expected state value (e.g., "on", "off").
    """
    
    type: Literal["state"] = "state"
    entity: str
    is_state: str = Field(..., alias="is")
    
    @field_validator("entity")
    @classmethod
    def validate_entity_id(cls, v: str) -> str:
        """Validate entity ID format."""
        if "." not in v:
            raise ValueError(f"Entity ID must be in domain.entity format: {v}")
        return v


class NumericGuardConfig(BaseModel):
    """Configuration for numeric comparison guard.
    
    Attributes:
        type: Guard type identifier ("numeric").
        entity: Sensor entity ID to check.
        operator: Comparison operator ("<", ">", "<=", ">=", "==").
        value: Threshold value for comparison.
    """
    
    type: Literal["numeric"] = "numeric"
    entity: str
    operator: Literal["<", ">", "<=", ">=", "=="]
    value: float
    
    @field_validator("entity")
    @classmethod
    def validate_entity_id(cls, v: str) -> str:
        """Validate entity ID format."""
        if "." not in v:
            raise ValueError(f"Entity ID must be in domain.entity format: {v}")
        return v


class ScheduleGuardConfig(BaseModel):
    """Configuration for schedule-based guard.
    
    Attributes:
        type: Guard type identifier ("schedule").
        days: List of days (e.g., ["mon", "tue", "wed", "thu", "fri"]).
        between: Time range in "HH:MM-HH:MM" format.
    """
    
    type: Literal["schedule"] = "schedule"
    days: list[str] = Field(default_factory=list)
    between: str
    
    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[str]) -> list[str]:
        """Validate day names."""
        valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun", 
                      "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        valid_ranges = {"mon-fri", "sat-sun", "daily"}
        
        for day in v:
            day_lower = day.lower()
            if day_lower not in valid_days and day_lower not in valid_ranges:
                raise ValueError(f"Invalid day: {day}. Must be mon-sun or mon-fri, sat-sun, daily")
        
        return v
    
    @field_validator("between")
    @classmethod
    def validate_time_range(cls, v: str) -> str:
        """Validate time range format."""
        from datetime import datetime
        
        if "-" not in v:
            raise ValueError("Time range must be in 'HH:MM-HH:MM' format")
        
        parts = v.split("-")
        if len(parts) != 2:
            raise ValueError("Time range must have exactly start and end times")
        
        for part in parts:
            try:
                datetime.strptime(part.strip(), "%H:%M")
            except ValueError:
                raise ValueError(f"Invalid time format: {part}. Expected HH:MM")
        
        return v


class CompositeGuardConfig(BaseModel):
    """Configuration for composite AND/OR guard.
    
    Attributes:
        type: Guard type identifier ("and" or "or").
        conditions: List of nested guard configurations.
    """
    
    type: Literal["and", "or"]
    conditions: list[GuardConfig] = Field(default_factory=list)


# Forward reference for recursive type
GuardConfig = (
    TimeGuardConfig 
    | StateGuardConfig 
    | NumericGuardConfig 
    | ScheduleGuardConfig 
    | CompositeGuardConfig
)


class GuardFactoryModel(BaseModel):
    """Union model for all guard types with discriminator."""
    
    guard: TimeGuardConfig | StateGuardConfig | NumericGuardConfig | ScheduleGuardConfig | CompositeGuardConfig
    
    @classmethod
    def parse_guard(cls, data: dict[str, Any]) -> TimeGuardConfig | StateGuardConfig | NumericGuardConfig | ScheduleGuardConfig | CompositeGuardConfig:
        """Parse guard configuration into appropriate model.
        
        Args:
            data: Dictionary with guard configuration.
            
        Returns:
            Appropriate guard configuration model.
            
        Raises:
            ValueError: If guard type is unknown or configuration is invalid.
        """
        guard_type = data.get("type")
        
        if guard_type == "time":
            return TimeGuardConfig.model_validate(data)
        elif guard_type == "state":
            return StateGuardConfig.model_validate(data)
        elif guard_type == "numeric":
            return NumericGuardConfig.model_validate(data)
        elif guard_type == "schedule":
            return ScheduleGuardConfig.model_validate(data)
        elif guard_type in ("and", "or"):
            return CompositeGuardConfig.model_validate(data)
        else:
            raise ValueError(f"Unknown guard type: {guard_type}")
