"""Модели для Digital Twin / Simulator."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SimulationMode(str, Enum):
    """Режимы симуляции."""
    
    REAL_TIME = "real_time"
    FAST_FORWARD = "fast_forward"
    STEP_BY_STEP = "step_by_step"


class SimulationEvent(BaseModel):
    """Событие симуляции."""
    
    timestamp: datetime = Field(default_factory=datetime.now)
    event_type: str = Field(..., description="Тип события (sensor.update, command.execute)")
    source: str = Field(..., description="Источник события")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Данные события")
    room_id: Optional[str] = Field(None, description="ID комнаты")
    
    class Config:
        arbitrary_types_allowed = True


class SimulationState(BaseModel):
    """Состояние симуляции."""
    
    is_running: bool = Field(default=False, description="Запущена ли симуляция")
    current_time: datetime = Field(default_factory=datetime.now, description="Текущее время симуляции")
    start_time: Optional[datetime] = Field(None, description="Время начала симуляции")
    end_time: Optional[datetime] = Field(None, description="Время окончания симуляции")
    mode: SimulationMode = Field(default=SimulationMode.REAL_TIME, description="Режим симуляции")
    speed_multiplier: float = Field(default=1.0, ge=0.1, le=1000.0, description="Множитель скорости")
    step_count: int = Field(default=0, description="Количество шагов в step_by_step режиме")
    events_processed: int = Field(default=0, description="Количество обработанных событий")
    
    class Config:
        arbitrary_types_allowed = True


class SensorSimulationConfig(BaseModel):
    """Конфигурация симуляции сенсора."""
    
    sensor_id: str = Field(..., description="ID сенсора")
    initial_value: Any = Field(None, description="Начальное значение")
    variation_pattern: str = Field(default="constant", description="Паттерн изменения значения")
    variation_params: Dict[str, Any] = Field(default_factory=dict, description="Параметры вариации")
    update_interval: float = Field(default=60.0, ge=0.1, description="Интервал обновления в секундах")
    
    # Паттерны: constant, random, sinusoidal, step, trend
    # variation_params для каждого паттерна:
    # - random: {"min": 0, "max": 100}
    # - sinusoidal: {"amplitude": 10, "period": 3600, "offset": 50}
    # - step: {"steps": [{"time": 0, "value": 20}, {"time": 300, "value": 25}]}
    # - trend: {"start": 20, "end": 30, "duration": 7200}


class ScenarioStep(BaseModel):
    """Шаг сценария симуляции."""
    
    delay: float = Field(ge=0, description="Задержка перед шагом в секундах")
    actions: List[Dict[str, Any]] = Field(default_factory=list, description="Действия для выполнения")
    conditions: Optional[Dict[str, Any]] = Field(None, description="Условия выполнения шага")
    description: Optional[str] = Field(None, description="Описание шага")


class SimulationScenario(BaseModel):
    """Сценарий симуляции."""
    
    name: str = Field(..., description="Название сценария")
    description: Optional[str] = Field(None, description="Описание сценария")
    duration: Optional[float] = Field(None, ge=0, description="Длительность сценария в секундах")
    steps: List[ScenarioStep] = Field(default_factory=list, description="Шаги сценария")
    sensor_configs: List[SensorSimulationConfig] = Field(default_factory=list, description="Конфигурации сенсоров")
    initial_states: Dict[str, Any] = Field(default_factory=dict, description="Начальные состояния")


class SimulationReport(BaseModel):
    """Отчет о симуляции."""
    
    scenario_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_real: float = Field(default=0.0, description="Реальная длительность в секундах")
    duration_simulated: float = Field(default=0.0, description="Симулированная длительность в секундах")
    events_generated: int = Field(default=0, description="Количество сгенерированных событий")
    events_processed: int = Field(default=0, description="Количество обработанных событий")
    commands_executed: int = Field(default=0, description="Количество выполненных команд")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="Ошибки во время симуляции")
    warnings: List[Dict[str, Any]] = Field(default_factory=list, description="Предупреждения")
    final_state: Dict[str, Any] = Field(default_factory=dict, description="Финальное состояние")
    
    class Config:
        arbitrary_types_allowed = True
