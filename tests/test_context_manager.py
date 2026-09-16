"""
Tests for Context Manager component.

Specification:
1. ContextManager должен управлять контекстом FSM на основе сенсоров HA
2. Должна быть поддержка подписки на сенсоры (движение, освещенность, температура)
3. Должна быть поддержка расписаний времени (ночь/день, активные часы)
4. Контекст должен автоматически обновляться при изменении состояний сенсоров
5. При изменении контекста должен публиковаться событие context.changed
6. Поддержка пользовательских условий (отпуск, гости и т.д.)
7. TimeRange должен корректно обрабатывать переход через полночь
8. ContextManager должен подписываться на события ha.state_changed и platform.started
9. Подписка на сенсоры использует entity_id -> context_key маппинг
10. При старте платформы запускается периодическая проверка расписаний
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.context_manager import ContextManager, TimeRange


class MockFSMEngine:
    """Mock FSM Engine для тестов."""

    def __init__(self):
        self._contexts = {}
        self._triggered = []

    def get_context(self, entity_id):
        return self._contexts.get(entity_id, {})

    def update_context(self, entity_id, context_updates):
        if entity_id not in self._contexts:
            self._contexts[entity_id] = {}
        self._contexts[entity_id].update(context_updates)

    def trigger(self, entity_id, trigger_name, data=None):
        self._triggered.append((entity_id, trigger_name, data))


@pytest.fixture
def mock_event_bus():
    """Создаёт mock event bus."""
    bus = MagicMock()
    bus.subscribe = MagicMock()
    bus.publish = MagicMock()
    return bus


@pytest.fixture
def mock_fsm_engine():
    """Создаёт mock FSM engine."""
    return MockFSMEngine()


@pytest.fixture
def mock_logger():
    """Создаёт mock logger."""
    logger = MagicMock()
    logger.info = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def context_manager(mock_event_bus, mock_fsm_engine, mock_logger):
    """Создаёт экземпляр ContextManager для тестов."""
    return ContextManager(
        event_bus=mock_event_bus,
        fsm_engine=mock_fsm_engine,
        logger=mock_logger,
    )


class TestTimeRange:
    """Тесты класса TimeRange."""

    def test_creates_from_string(self):
        """Создание TimeRange из строки 'HH:MM' - возвращает диапазон от HH:MM до 00:00."""
        tr = TimeRange.from_string("07:30")
        assert tr.start_hour == 7
        assert tr.start_minute == 30
        assert tr.end_hour == 0
        assert tr.end_minute == 0

    def test_is_within_normal_range(self):
        """Проверка попадания в обычный диапазон (без перехода через полночь)."""
        tr = TimeRange(8, 0, 18, 0)  # 08:00 - 18:00
        
        assert tr.is_within(10, 0) is True
        assert tr.is_within(14, 30) is True
        assert tr.is_within(7, 59) is False
        assert tr.is_within(18, 1) is False

    def test_is_within_midnight_crossing_range(self):
        """Проверка диапазона с переходом через полночь."""
        tr = TimeRange(22, 0, 6, 0)  # 22:00 - 06:00
        
        assert tr.is_within(23, 0) is True
        assert tr.is_within(5, 0) is True
        assert tr.is_within(12, 0) is False
        assert tr.is_within(21, 59) is False
        assert tr.is_within(6, 1) is False

    def test_boundary_conditions(self):
        """Проверка граничных условий."""
        tr = TimeRange(10, 0, 12, 0)
        
        assert tr.is_within(10, 0) is True  # Начало диапазона
        assert tr.is_within(12, 0) is True  # Конец диапазона
        assert tr.is_within(9, 59) is False
        assert tr.is_within(12, 1) is False


class TestContextManagerInitialization:
    """Тесты инициализации ContextManager."""

    def test_initializes_with_empty_subscriptions(self, context_manager):
        """При инициализации список подписок пуст."""
        assert context_manager._sensor_subscriptions == {}
        assert context_manager._schedules == {}

    def test_subscribes_to_ha_state_changed_event(self, mock_event_bus, context_manager):
        """ContextManager подписывается на ha.state_changed."""
        calls = [call[0][0] for call in mock_event_bus.subscribe.call_args_list]
        assert "ha.state_changed" in calls

    def test_subscribes_to_platform_started_event(self, mock_event_bus, context_manager):
        """ContextManager подписывается на platform.started."""
        calls = [call[0][0] for call in mock_event_bus.subscribe.call_args_list]
        assert "platform.started" in calls

    def test_logs_initialization(self, mock_logger, context_manager):
        """Логирование при инициализации."""
        mock_logger.info.assert_called()


class TestSubscribeSensor:
    """Тесты метода subscribe_sensor()."""

    def test_subscribes_to_sensor(self, context_manager):
        """Подписка на сенсор движения."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion",
            "living_room_motion_sensor"
        )
        
        assert "living_room_motion_sensor" in context_manager._sensor_subscriptions
        assert context_manager._sensor_subscriptions["living_room_motion_sensor"] == {
            "sensor_entity": "binary_sensor.living_room_motion",
            "context_key": "motion_detected"
        }

    def test_subscribes_with_custom_context_key(self, context_manager):
        """Подписка с кастомным ключом контекста."""
        context_manager.subscribe_sensor(
            "binary_sensor.kitchen_motion",
            "kitchen_motion_sensor",
            context_key="kitchen_motion"
        )
        
        assert context_manager._sensor_subscriptions["kitchen_motion_sensor"]["context_key"] == "kitchen_motion"

    def test_subscribes_multiple_sensors(self, context_manager):
        """Можно подписаться на несколько сенсоров."""
        context_manager.subscribe_sensor("binary_sensor.motion1", "entity1")
        context_manager.subscribe_sensor("binary_sensor.motion2", "entity2")
        context_manager.subscribe_sensor("sensor.light1", "entity3")
        
        assert len(context_manager._sensor_subscriptions) == 3

    def test_logs_subscription(self, context_manager, mock_logger):
        """Логирование подписки на сенсор."""
        context_manager.subscribe_sensor("binary_sensor.test", "test_entity")
        
        mock_logger.info.assert_any_call("Subscribed test_entity to binary_sensor.test")


class TestScheduleTimeCheck:
    """Тесты метода schedule_time_check()."""

    def test_schedules_time_check(self, context_manager):
        """Планирование проверки времени."""
        context_manager.schedule_time_check(
            "living_room_is_schedule_time",
            "07:00",
            "23:00"
        )
        
        assert "living_room_is_schedule_time" in context_manager._time_checks
        time_check = context_manager._time_checks["living_room_is_schedule_time"]
        assert time_check["start_hour"] == 7
        assert time_check["start_minute"] == 0
        assert time_check["end_hour"] == 23
        assert time_check["end_minute"] == 0

    def test_schedules_with_custom_context_key(self, context_manager):
        """Планирование с кастомным ключом контекста."""
        context_manager.schedule_time_check(
            "bedroom_night_mode",
            "22:00",
            "07:00",
            context_key="is_night"
        )
        
        time_check = context_manager._time_checks["bedroom_night_mode"]
        assert time_check["context_key"] == "is_night"
        assert time_check["start_hour"] == 22
        assert time_check["end_hour"] == 7  # Переход через полночь

    def test_schedules_multiple_time_checks(self, context_manager):
        """Можно запланировать несколько проверок времени."""
        context_manager.schedule_time_check("entity1", "08:00", "18:00")
        context_manager.schedule_time_check("entity2", "22:00", "06:00")
        
        assert len(context_manager._time_checks) == 2

    def test_logs_time_check(self, context_manager, mock_logger):
        """Логирование планирования проверки времени."""
        context_manager.schedule_time_check("test_entity", "07:00", "23:00")
        
        mock_logger.info.assert_any_call("Scheduled time check for test_entity: 07:00-23:00")


class TestOnStateChanged:
    """Тесты обработчика изменения состояний."""

    def test_updates_context_on_sensor_change(self, context_manager, mock_fsm_engine):
        """Обновление контекста при изменении состояния сенсора."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion",
            "living_room_motion_sensor"
        )
        
        # Событие: движение обнаружено
        event_data = {
            "entity_id": "binary_sensor.living_room_motion",
            "new_state": "on"
        }
        
        context_manager._on_state_changed(event_data)
        
        # Проверяем что контекст был обновлён
        context = mock_fsm_engine.get_context("living_room_motion_sensor")
        assert context.get("motion_detected") is True

    def test_updates_context_on_sensor_off(self, context_manager, mock_fsm_engine):
        """Обновление контекста при пропадании движения."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion",
            "living_room_motion_sensor"
        )
        
        # Сначала включаем
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.living_room_motion",
            "new_state": "on"
        })
        
        # Затем выключаем
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.living_room_motion",
            "new_state": "off"
        })
        
        context = mock_fsm_engine.get_context("living_room_motion_sensor")
        assert context.get("motion_detected") is False

    def test_ignores_unsubscribed_sensor(self, context_manager, mock_fsm_engine):
        """Игнорирование неподписанного сенсора."""
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.unknown",
            "new_state": "on"
        })
        
        assert mock_fsm_engine._triggered == []

    def test_triggers_fsm_on_context_change(self, context_manager, mock_fsm_engine):
        """Триггер FSM при изменении контекста."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion",
            "living_room_motion_sensor"
        )
        
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.living_room_motion",
            "new_state": "on"
        })
        
        assert len(mock_fsm_engine._triggered) > 0
        triggered_entity, trigger_name, _ = mock_fsm_engine._triggered[0]
        assert triggered_entity == "living_room_motion_sensor"
        assert trigger_name == "context_changed"

    def test_handles_boolean_states(self, context_manager, mock_fsm_engine):
        """Обработка булевых состояний сенсоров."""
        context_manager.subscribe_sensor(
            "binary_sensor.door",
            "door_sensor",
            context_key="door_open"
        )
        
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.door",
            "new_state": "on"
        })
        
        context = mock_fsm_engine.get_context("door_sensor")
        assert context.get("door_open") is True


class TestOnPlatformStarted:
    """Тесты восстановления контекстов при старте платформы."""

    def test_reads_sensor_states_on_start(self, context_manager, mock_event_bus, mock_fsm_engine):
        """Чтение состояний сенсоров при старте платформы."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion",
            "living_room_motion_sensor"
        )
        
        # Мок получения состояния от адаптера
        with patch.object(context_manager, '_get_sensor_state', return_value="on"):
            context_manager._on_platform_started({})
        
        context = mock_fsm_engine.get_context("living_room_motion_sensor")
        assert context.get("motion_detected") is True

    def test_evaluates_time_checks_on_start(self, context_manager, mock_fsm_engine):
        """Проверка временных диапазонов при старте."""
        # Устанавливаем время в диапазоне
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 10
            mock_datetime.now.return_value.minute = 30
            
            context_manager.schedule_time_check(
                "living_room_is_schedule_time",
                "07:00",
                "23:00"
            )
            
            context_manager._on_platform_started({})
        
        context = mock_fsm_engine.get_context("living_room_is_schedule_time")
        assert context.get("is_schedule_time") is True

    def test_evaluates_time_checks_outside_range(self, context_manager, mock_fsm_engine):
        """Проверка вне временного диапазона."""
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 3
            mock_datetime.now.return_value.minute = 0
            
            context_manager.schedule_time_check(
                "living_room_is_schedule_time",
                "07:00",
                "23:00"
            )
            
            context_manager._on_platform_started({})
        
        context = mock_fsm_engine.get_context("living_room_is_schedule_time")
        assert context.get("is_schedule_time") is False


class TestCheckTimeAndUpdate:
    """Тесты метода check_time_and_update()."""

    def test_updates_context_when_in_range(self, context_manager, mock_fsm_engine):
        """Обновление контекста когда время в диапазоне."""
        context_manager.schedule_time_check(
            "living_room_is_schedule_time",
            "07:00",
            "23:00"
        )
        
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 12
            mock_datetime.now.return_value.minute = 0
            
            context_manager.check_time_and_update("living_room_is_schedule_time")
        
        context = mock_fsm_engine.get_context("living_room_is_schedule_time")
        assert context.get("is_schedule_time") is True

    def test_updates_context_when_outside_range(self, context_manager, mock_fsm_engine):
        """Обновление контекста когда время вне диапазона."""
        context_manager.schedule_time_check(
            "living_room_is_schedule_time",
            "07:00",
            "23:00"
        )
        
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 2
            mock_datetime.now.return_value.minute = 0
            
            context_manager.check_time_and_update("living_room_is_schedule_time")
        
        context = mock_fsm_engine.get_context("living_room_is_schedule_time")
        assert context.get("is_schedule_time") is False

    def test_handles_midnight_crossing(self, context_manager, mock_fsm_engine):
        """Обработка перехода через полночь."""
        context_manager.schedule_time_check(
            "bedroom_night_mode",
            "22:00",
            "06:00"
        )
        
        # Время 23:00 - должно быть в диапазоне
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 23
            mock_datetime.now.return_value.minute = 0
            
            context_manager.check_time_and_update("bedroom_night_mode")
        
        context = mock_fsm_engine.get_context("bedroom_night_mode")
        assert context.get("is_night_mode") is True

    def test_triggers_fsm_on_time_change(self, context_manager, mock_fsm_engine):
        """Триггер FSM при изменении временного контекста."""
        context_manager.schedule_time_check(
            "living_room_is_schedule_time",
            "07:00",
            "23:00"
        )
        
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 10
            mock_datetime.now.return_value.minute = 0
            
            context_manager.check_time_and_update("living_room_is_schedule_time")
        
        assert len(mock_fsm_engine._triggered) > 0


class TestGetSensorState:
    """Тесты метода _get_sensor_state()."""

    @pytest.mark.asyncio
    async def test_gets_state_via_adapter(self, context_manager):
        """Получение состояния сенсора через адаптер."""
        context_manager._adapter = MagicMock()
        context_manager._adapter.get_entity_state = AsyncMock(return_value="on")
        
        state = await context_manager._get_sensor_state("binary_sensor.test")
        
        assert state == "on"
        context_manager._adapter.get_entity_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, context_manager):
        """Возврат None при ошибке получения состояния."""
        context_manager._adapter = MagicMock()
        context_manager._adapter.get_entity_state = AsyncMock(side_effect=Exception("Error"))
        
        state = await context_manager._get_sensor_state("binary_sensor.test")
        
        assert state is None


class TestIntegrationScenarios:
    """Интеграционные сценарии использования ContextManager."""

    def test_motion_sensor_workflow(self, context_manager, mock_fsm_engine):
        """Сценарий: датчик движения включает свет."""
        # Подписка на датчик движения
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion",
            "light.living_room"
        )
        
        # Движение обнаружено
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.living_room_motion",
            "new_state": "on"
        })
        
        # Контекст обновлён
        context = mock_fsm_engine.get_context("light.living_room")
        assert context.get("motion_detected") is True
        
        # FSM был затриггерен
        assert any(t[0] == "light.living_room" for t in mock_fsm_engine._triggered)

    def test_schedule_based_lighting(self, context_manager, mock_fsm_engine):
        """Сценарий: освещение по расписанию."""
        # Подписка на расписание
        context_manager.schedule_time_check(
            "light.hallway",
            "18:00",
            "23:00"
        )
        
        # Вечернее время
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 20
            mock_datetime.now.return_value.minute = 0
            
            context_manager._on_platform_started({})
        
        context = mock_fsm_engine.get_context("light.hallway")
        assert context.get("is_schedule_time") is True

    def test_combined_motion_and_schedule(self, context_manager, mock_fsm_engine):
        """Сценарий: комбинация движения и расписания."""
        # Датчик движения
        context_manager.subscribe_sensor(
            "binary_sensor.bedroom_motion",
            "light.bedroom"
        )
        
        # Расписание (ночной режим)
        context_manager.schedule_time_check(
            "light.bedroom",
            "22:00",
            "06:00",
            context_key="is_night"
        )
        
        # Ночное время + движение
        with patch("core.context_manager.datetime") as mock_datetime:
            mock_datetime.now.return_value.hour = 23
            mock_datetime.now.return_value.minute = 0
            
            context_manager._on_platform_started({})
        
        context_manager._on_state_changed({
            "entity_id": "binary_sensor.bedroom_motion",
            "new_state": "on"
        })
        
        context = mock_fsm_engine.get_context("light.bedroom")
        assert context.get("motion_detected") is True
        assert context.get("is_night") is True
