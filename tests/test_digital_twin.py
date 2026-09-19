"""Тесты для Digital Twin / Simulator."""

import asyncio
import pytest
from datetime import datetime, timedelta

from src.core.simulator import DigitalTwin, SensorSimulator
from src.core.models.simulation import (
    SimulationMode,
    SimulationScenario,
    SensorSimulationConfig,
    ScenarioStep,
    SimulationEvent,
)


class TestSensorSimulator:
    """Тесты для SensorSimulator."""
    
    def test_constant_pattern(self):
        """Тест постоянного паттерна."""
        config = SensorSimulationConfig(
            sensor_id="sensor_1",
            initial_value=25.0,
            variation_pattern="constant",
        )
        simulator = SensorSimulator(config=config)
        
        value = simulator.get_next_value(datetime.now())
        assert value == 25.0
        
        value = simulator.get_next_value(datetime.now() + timedelta(seconds=10))
        assert value == 25.0
    
    def test_random_pattern(self):
        """Тест случайного паттерна."""
        config = SensorSimulationConfig(
            sensor_id="sensor_2",
            initial_value=50.0,
            variation_pattern="random",
            variation_params={"min": 0, "max": 100},
        )
        simulator = SensorSimulator(config=config)
        
        value = simulator.get_next_value(datetime.now())
        assert 0 <= value <= 100
        
        value2 = simulator.get_next_value(datetime.now() + timedelta(seconds=1))
        assert 0 <= value2 <= 100
    
    def test_sinusoidal_pattern(self):
        """Тест синусоидального паттерна."""
        config = SensorSimulationConfig(
            sensor_id="sensor_3",
            initial_value=50.0,
            variation_pattern="sinusoidal",
            variation_params={"amplitude": 10, "period": 60, "offset": 50},
        )
        simulator = SensorSimulator(config=config)
        
        now = datetime.now()
        value1 = simulator.get_next_value(now)
        value2 = simulator.get_next_value(now + timedelta(seconds=30))  # половина периода
        
        # Значения должны быть в диапазоне [40, 60]
        assert 40 <= value1 <= 60
        assert 40 <= value2 <= 60
    
    def test_step_pattern(self):
        """Тест пошагового паттерна."""
        config = SensorSimulationConfig(
            sensor_id="sensor_4",
            initial_value=20.0,
            variation_pattern="step",
            variation_params={
                "steps": [
                    {"time": 0, "value": 20},
                    {"time": 10, "value": 25},
                    {"time": 20, "value": 30},
                ]
            },
        )
        simulator = SensorSimulator(config=config)
        
        now = datetime.now()
        value1 = simulator.get_next_value(now)
        assert value1 == 20
        
        value2 = simulator.get_next_value(now + timedelta(seconds=15))
        assert value2 == 25
        
        # Третий шаг - нужно симулировать прохождение времени с последнего обновления
        simulator.last_update = now  # сбросить last_update для корректного теста
        value3 = simulator.get_next_value(now + timedelta(seconds=25))
        assert value3 == 30
    
    def test_trend_pattern(self):
        """Тест тренда."""
        config = SensorSimulationConfig(
            sensor_id="sensor_5",
            initial_value=20.0,
            variation_pattern="trend",
            variation_params={"start": 20, "end": 30, "duration": 60},
        )
        simulator = SensorSimulator(config=config)
        
        now = datetime.now()
        value1 = simulator.get_next_value(now)
        assert abs(value1 - 20) < 0.1  # начало тренда
        
        value2 = simulator.get_next_value(now + timedelta(seconds=30))  # половина duration
        assert 24 <= value2 <= 26  # примерно посередине
        
        # Для третьего значения нужно сбросить last_update, чтобы elapsed был равен 60 секундам
        simulator.last_update = now
        value3 = simulator.get_next_value(now + timedelta(seconds=60))  # конец duration
        assert abs(value3 - 30) < 0.1


class TestDigitalTwin:
    """Тесты для DigitalTwin."""
    
    @pytest.mark.asyncio
    async def test_initialization(self):
        """Тест инициализации."""
        twin = DigitalTwin()
        state = twin.get_state()
        
        assert not state.is_running
        assert state.mode == SimulationMode.REAL_TIME
        assert state.speed_multiplier == 1.0
    
    @pytest.mark.asyncio
    async def test_load_scenario(self):
        """Тест загрузки сценария."""
        twin = DigitalTwin()
        
        scenario = SimulationScenario(
            name="Test Scenario",
            description="Test description",
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="temp_sensor",
                    initial_value=22.0,
                    variation_pattern="constant",
                )
            ],
        )
        
        await twin.load_scenario(scenario)
        assert twin._scenario is not None
        assert twin._scenario.name == "Test Scenario"
        assert len(twin.sensor_simulators) == 1
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Тест запуска и остановки."""
        twin = DigitalTwin()
        
        scenario = SimulationScenario(
            name="Test",
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="sensor_1",
                    initial_value=25.0,
                    variation_pattern="constant",
                    update_interval=0.1,  # быстрое обновление для теста
                )
            ],
        )
        
        await twin.load_scenario(scenario)
        await twin.start(mode=SimulationMode.REAL_TIME)
        
        assert twin.get_state().is_running
        
        await asyncio.sleep(0.5)  # подождать немного
        
        await twin.stop()
        assert not twin.get_state().is_running
    
    @pytest.mark.asyncio
    async def test_fast_forward_mode(self):
        """Тест режима ускорения."""
        twin = DigitalTwin()
        
        scenario = SimulationScenario(
            name="Fast Forward Test",
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="sensor_1",
                    initial_value=25.0,
                    variation_pattern="constant",
                    update_interval=0.1,
                )
            ],
        )
        
        await twin.load_scenario(scenario)
        await twin.start(mode=SimulationMode.FAST_FORWARD, speed_multiplier=10.0)
        
        assert twin.get_state().speed_multiplier == 10.0
        
        await asyncio.sleep(0.3)
        await twin.stop()
        
        report = twin.get_report()
        assert report.events_generated > 0
    
    @pytest.mark.asyncio
    async def test_event_callback(self):
        """Тест callback для событий."""
        events_received = []
        
        async def event_callback(event):
            events_received.append(event)
        
        twin = DigitalTwin(event_callback=event_callback)
        
        scenario = SimulationScenario(
            name="Callback Test",
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="sensor_1",
                    initial_value=25.0,
                    variation_pattern="constant",
                    update_interval=0.1,
                )
            ],
        )
        
        await twin.load_scenario(scenario)
        await twin.start(mode=SimulationMode.REAL_TIME)
        
        await asyncio.sleep(0.5)
        await twin.stop()
        
        assert len(events_received) > 0
        assert all(e.event_type == "sensor.update" for e in events_received)
    
    @pytest.mark.asyncio
    async def test_get_report(self):
        """Тест получения отчета."""
        twin = DigitalTwin()
        
        scenario = SimulationScenario(
            name="Report Test",
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="sensor_1",
                    initial_value=25.0,
                    variation_pattern="constant",
                    update_interval=0.1,
                )
            ],
        )
        
        await twin.load_scenario(scenario)
        await twin.start()
        await asyncio.sleep(0.3)
        await twin.stop()
        
        report = twin.get_report()
        assert report.scenario_name == "Report Test"
        assert report.start_time is not None
        assert report.end_time is not None
        assert report.duration_real > 0
        assert report.events_generated > 0
    
    @pytest.mark.asyncio
    async def test_double_start_error(self):
        """Тест ошибки при повторном запуске."""
        twin = DigitalTwin()
        
        scenario = SimulationScenario(
            name="Double Start Test",
            sensor_configs=[],
        )
        
        await twin.load_scenario(scenario)
        await twin.start()
        
        with pytest.raises(RuntimeError, match="Симуляция уже запущена"):
            await twin.start()
        
        await twin.stop()
    
    @pytest.mark.asyncio
    async def test_step_mode(self):
        """Тест пошагового режима."""
        twin = DigitalTwin()
        
        scenario = SimulationScenario(
            name="Step Mode Test",
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="sensor_1",
                    initial_value=25.0,
                    variation_pattern="constant",
                    update_interval=0.1,
                )
            ],
        )
        
        await twin.load_scenario(scenario)
        await twin.start(mode=SimulationMode.STEP_BY_STEP)
        
        # Выполнить несколько шагов
        events1 = await twin.step()
        events2 = await twin.step()
        
        assert twin.get_state().step_count == 2
        
        await twin.stop()


class TestSimulationScenario:
    """Тесты для SimulationScenario."""
    
    def test_scenario_creation(self):
        """Тест создания сценария."""
        scenario = SimulationScenario(
            name="Morning Routine",
            description="Симуляция утреннего распорядка",
            duration=3600,  # 1 час
            steps=[
                ScenarioStep(
                    delay=0,
                    actions=[{"type": "set_temperature", "value": 22}],
                    description="Начало симуляции",
                ),
                ScenarioStep(
                    delay=300,  # 5 минут
                    actions=[{"type": "turn_on_lights"}],
                    description="Включение света",
                ),
            ],
            sensor_configs=[
                SensorSimulationConfig(
                    sensor_id="bedroom_temp",
                    initial_value=20.0,
                    variation_pattern="trend",
                    variation_params={"start": 20, "end": 23, "duration": 1800},
                )
            ],
        )
        
        assert scenario.name == "Morning Routine"
        assert len(scenario.steps) == 2
        assert len(scenario.sensor_configs) == 1
        assert scenario.duration == 3600
    
    def test_minimal_scenario(self):
        """Тест минимального сценария."""
        scenario = SimulationScenario(
            name="Minimal",
        )
        
        assert scenario.name == "Minimal"
        assert scenario.steps == []
        assert scenario.sensor_configs == []
        assert scenario.description is None
