"""Digital Twin / Simulator - симуляция работы умного дома."""

import asyncio
import contextlib
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .models.simulation import (
    SensorSimulationConfig,
    SimulationEvent,
    SimulationMode,
    SimulationReport,
    SimulationScenario,
    SimulationState,
)


@dataclass
class SensorSimulator:
    """Симулятор одного сенсора."""

    config: SensorSimulationConfig
    current_value: Any = None
    last_update: datetime | None = None

    def __post_init__(self):
        """Инициализация начального значения."""
        if self.current_value is None:
            self.current_value = self.config.initial_value
        self.last_update = datetime.now()

    def get_next_value(self, simulation_time: datetime) -> Any:
        """Получить следующее значение сенсора."""
        pattern = self.config.variation_pattern

        if pattern == "constant":
            value = self.config.initial_value
        elif pattern == "random":
            params = self.config.variation_params
            value = random.uniform(params.get("min", 0), params.get("max", 100))
        elif pattern == "sinusoidal":
            params = self.config.variation_params
            amplitude = params.get("amplitude", 10)
            period = params.get("period", 3600)
            offset = params.get("offset", 50)
            elapsed = (
                (simulation_time - self.last_update).total_seconds() if self.last_update else 0
            )
            value = offset + amplitude * math.sin(2 * math.pi * elapsed / period)
        elif pattern == "step":
            params = self.config.variation_params
            steps = params.get("steps", [])
            elapsed = (
                (simulation_time - self.last_update).total_seconds() if self.last_update else 0
            )
            value = self.config.initial_value
            for step in sorted(steps, key=lambda x: x["time"]):
                if elapsed >= step["time"]:
                    value = step["value"]
        elif pattern == "trend":
            params = self.config.variation_params
            start = params.get("start", 20)
            end = params.get("end", 30)
            duration = params.get("duration", 7200)
            elapsed = (
                (simulation_time - self.last_update).total_seconds() if self.last_update else 0
            )
            progress = min(elapsed / duration, 1.0)
            value = start + (end - start) * progress
        else:
            value = self.config.initial_value

        self.current_value = value
        self.last_update = simulation_time
        return value


class DigitalTwin:
    """Digital Twin - симулятор умного дома."""

    def __init__(self, event_callback: Callable | None = None):
        """
        Инициализация симулятора.

        Args:
            event_callback: Callback для обработки событий симуляции
        """
        self.state = SimulationState()
        self.sensor_simulators: dict[str, SensorSimulator] = {}
        self.event_callback = event_callback
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None
        self._scenario: SimulationScenario | None = None
        self._report = SimulationReport(
            scenario_name="",
            start_time=datetime.now(),
        )

    async def load_scenario(self, scenario: SimulationScenario) -> None:
        """
        Загрузить сценарий симуляции.

        Args:
            scenario: Сценарий для загрузки
        """
        self._scenario = scenario
        self._report = SimulationReport(
            scenario_name=scenario.name,
            start_time=datetime.now(),
        )

        # Инициализация симуляторов сенсоров
        self.sensor_simulators = {}
        for sensor_config in scenario.sensor_configs:
            simulator = SensorSimulator(config=sensor_config)
            self.sensor_simulators[sensor_config.sensor_id] = simulator

        # Установка начальных состояний
        self.state.current_time = datetime.now()

    async def start(
        self, mode: SimulationMode = SimulationMode.REAL_TIME, speed_multiplier: float = 1.0
    ) -> None:
        """
        Запустить симуляцию.

        Args:
            mode: Режим симуляции
            speed_multiplier: Множитель скорости (только для FAST_FORWARD)
        """
        if self._running:
            raise RuntimeError("Симуляция уже запущена")

        self._running = True
        self.state.is_running = True
        self.state.mode = mode
        self.state.speed_multiplier = speed_multiplier
        self.state.start_time = datetime.now()

        if mode == SimulationMode.STEP_BY_STEP:
            self.state.step_count = 0

        self._task = asyncio.create_task(self._run_simulation())

    async def stop(self) -> None:
        """Остановить симуляцию."""
        self._running = False
        self.state.is_running = False
        self.state.end_time = datetime.now()

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        self._finalize_report()

    async def step(self) -> list[SimulationEvent]:
        """
        Выполнить один шаг симуляции (для STEP_BY_STEP режима).

        Returns:
            Список событий, сгенерированных на этом шаге
        """
        if not self._running or self.state.mode != SimulationMode.STEP_BY_STEP:
            raise RuntimeError("Симуляция не запущена или не в режиме STEP_BY_STEP")

        events = await self._process_step()
        self.state.step_count += 1
        return events

    async def _run_simulation(self) -> None:
        """Основной цикл симуляции."""
        try:
            if self.state.mode == SimulationMode.REAL_TIME:
                await self._run_real_time()
            elif self.state.mode == SimulationMode.FAST_FORWARD:
                await self._run_fast_forward()
            elif self.state.mode == SimulationMode.STEP_BY_STEP:
                # Ожидание вызова step()
                while self._running:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def _run_real_time(self) -> None:
        """Запуск в реальном времени."""
        # Инициализация last_update для первого события
        for simulator in self.sensor_simulators.values():
            if simulator.last_update is None:
                simulator.last_update = self.state.current_time - timedelta(
                    seconds=simulator.config.update_interval
                )

        while self._running:
            await self._process_step()
            await asyncio.sleep(0.1)  # Обновление каждые 100мс

    async def _run_fast_forward(self) -> None:
        """Запуск с ускорением."""
        # Инициализация last_update для первого события
        for simulator in self.sensor_simulators.values():
            if simulator.last_update is None:
                simulator.last_update = self.state.current_time - timedelta(
                    seconds=simulator.config.update_interval
                )

        interval = 1.0 / self.state.speed_multiplier
        while self._running:
            await self._process_step()
            await asyncio.sleep(interval)

    async def _process_step(self) -> list[SimulationEvent]:
        """Обработка одного шага симуляции."""
        events = []
        self.state.current_time = datetime.now()

        # Генерация событий от сенсоров
        for sensor_id, simulator in self.sensor_simulators.items():
            if simulator.config.update_interval <= 0:
                continue

            last_update = simulator.last_update or (
                self.state.current_time - timedelta(seconds=simulator.config.update_interval + 1)
            )
            elapsed = (self.state.current_time - last_update).total_seconds()

            if elapsed >= simulator.config.update_interval:
                value = simulator.get_next_value(self.state.current_time)
                event = SimulationEvent(
                    event_type="sensor.update",
                    source=sensor_id,
                    payload={"value": value, "sensor_id": sensor_id},
                )
                events.append(event)
                self.state.events_processed += 1
                self._report.events_generated += 1

                if self.event_callback:
                    await self.event_callback(event)

        # Обработка шагов сценария
        if self._scenario:
            await self._process_scenario_steps(events)

        return events

    async def _process_scenario_steps(self, events: list[SimulationEvent]) -> None:
        """Обработка шагов сценария."""
        # Простая реализация - может быть расширена
        pass

    def _finalize_report(self) -> None:
        """Финализация отчета о симуляции."""
        self._report.end_time = datetime.now()
        self._report.duration_real = (
            self._report.end_time - self._report.start_time
        ).total_seconds()

        if self.state.start_time and self.state.end_time:
            self._report.duration_simulated = (
                self.state.end_time - self.state.start_time
            ).total_seconds()

        self._report.events_processed = self.state.events_processed
        self._report.commands_executed = 0  # Может быть заполнено при интеграции

    def get_state(self) -> SimulationState:
        """Получить текущее состояние симуляции."""
        return self.state

    def get_report(self) -> SimulationReport:
        """Получить отчет о симуляции."""
        return self._report

    async def inject_event(self, event: SimulationEvent) -> None:
        """
        Инжектировать событие в симуляцию.

        Args:
            event: Событие для инжекции
        """
        if self.event_callback:
            await self.event_callback(event)
        self._report.events_processed += 1
