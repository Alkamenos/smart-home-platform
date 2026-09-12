"""
Declarative YAML Schema Definitions for FSM Automata.

This module provides Pydantic V2 models for validating YAML schemas
that define finite state machines for smart home automation.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class YAMLTransition(BaseModel):
    """
    YAML-схема для описания перехода между состояниями.

    Attributes:
        from_state: Исходное состояние для перехода.
        to_state: Целевое состояние после перехода.
        trigger: Событие, которое инициирует переход.
        guard: Имя функции-guard'а (строка), которая должна вернуть True.
        action: Имя функции-action (строка), которая будет выполнена.
        timeout_sec: Таймаут в секундах для автоматического перехода по событию 'timeout'.
    """

    from_state: str = Field(..., description="Исходное состояние")
    to_state: str = Field(..., description="Целевое состояние")
    trigger: str = Field(..., description="Событие триггера")
    guard: Optional[str] = Field(None, description="Имя функции guard для проверки условия")
    action: Optional[str] = Field(None, description="Имя функции action для выполнения")
    timeout_sec: Optional[float] = Field(None, ge=0, description="Таймаут в секундах")

    class Config:
        extra = "forbid"


class YAMLFSMDefinition(BaseModel):
    """
    YAML-схема для описания конечного автомата (FSM).

    Attributes:
        entity_id: Уникальный идентификатор сущности (например, 'light.kitchen').
        initial_state: Начальное состояние автомата.
        states: Список допустимых состояний.
        transitions: Список переходов между состояниями.
        debounce_sec: Минимальное время между переходами (защита от дребезга).
        params: Опциональные параметры для настройки поведения (из BehaviorConfig).
        target_device_id: ID целевого устройства для управления (оригинальный device.id).
    """

    entity_id: str = Field(..., description="Уникальный идентификатор сущности")
    initial_state: str = Field(..., description="Начальное состояние")
    states: list[str] = Field(..., min_length=1, description="Список допустимых состояний")
    transitions: list[YAMLTransition] = Field(..., min_length=1, description="Список переходов")
    debounce_sec: float = Field(0.0, ge=0, description="Защита от дребезга в секундах")
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры поведения из BehaviorConfig")
    target_device_id: Optional[str] = Field(None, description="ID целевого устройства для управления")

    class Config:
        extra = "forbid"
