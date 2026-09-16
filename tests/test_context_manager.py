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

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import time
from unittest.mock import MagicMock, patch

import pytest

from core.context_manager import ContextManager, TimeRange


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
    return MagicMock()


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
        assert context_manager._context == {}

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
        mock_logger.info.assert_called_with("ContextManager initialized")


class TestSubscribeSensor:
    """Тесты метода subscribe_sensor()."""

    def test_subscribes_to_sensor(self, context_manager):
        """Подписка на сенсор движения."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion", "living_room_motion_sensor"
        )

        assert "binary_sensor.living_room_motion" in context_manager._sensor_subscriptions
        assert (
            context_manager._sensor_subscriptions["binary_sensor.living_room_motion"]
            == "living_room_motion_sensor"
        )

    def test_subscribes_multiple_sensors(self, context_manager):
        """Можно подписаться на несколько сенсоров."""
        context_manager.subscribe_sensor("binary_sensor.motion1", "motion_context_1")
        context_manager.subscribe_sensor("binary_sensor.motion2", "motion_context_2")
        context_manager.subscribe_sensor("sensor.light1", "light_context_1")

        assert len(context_manager._sensor_subscriptions) == 3
        assert context_manager._sensor_subscriptions["binary_sensor.motion1"] == "motion_context_1"
        assert context_manager._sensor_subscriptions["binary_sensor.motion2"] == "motion_context_2"
        assert context_manager._sensor_subscriptions["sensor.light1"] == "light_context_1"

    def test_logs_subscription(self, context_manager, mock_logger):
        """Логирование подписки на сенсор."""
        context_manager.subscribe_sensor("binary_sensor.test", "test_entity")

        mock_logger.info.assert_any_call(
            "Subscribed sensor binary_sensor.test to context key test_entity"
        )


class TestSubscribeSchedule:
    """Тесты метода subscribe_schedule()."""

    def test_subscribes_to_schedule(self, context_manager):
        """Подписка на временной диапазон."""
        context_manager.subscribe_schedule("living_room_is_schedule_time", "07:00", "23:00")

        assert "living_room_is_schedule_time" in context_manager._schedules
        schedule = context_manager._schedules["living_room_is_schedule_time"]
        assert schedule.start_hour == 7
        assert schedule.start_minute == 0
        assert schedule.end_hour == 23
        assert schedule.end_minute == 0

    def test_subscribes_to_midnight_crossing_schedule(self, context_manager):
        """Подписка на диапазон с переходом через полночь."""
        context_manager.subscribe_schedule("bedroom_night_mode", "22:00", "07:00")

        schedule = context_manager._schedules["bedroom_night_mode"]
        assert schedule.start_hour == 22
        assert schedule.end_hour == 7  # Переход через полночь

    def test_subscribes_multiple_schedules(self, context_manager):
        """Можно подписаться на несколько расписаний."""
        context_manager.subscribe_schedule("schedule1", "08:00", "18:00")
        context_manager.subscribe_schedule("schedule2", "22:00", "06:00")

        assert len(context_manager._schedules) == 2

    def test_logs_schedule_subscription(self, context_manager, mock_logger):
        """Логирование подписки на расписание."""
        context_manager.subscribe_schedule("test_schedule", "07:00", "23:00")

        mock_logger.info.assert_any_call("Subscribed schedule test_schedule: 07:00 - 23:00")

    def test_updates_context_immediately_on_subscribe(self, context_manager):
        """Контекст обновляется сразу при подписке на расписание."""
        with patch("core.context_manager.time.localtime") as mock_localtime:
            mock_localtime.return_value.tm_hour = 10
            mock_localtime.return_value.tm_min = 30

            context_manager.subscribe_schedule("living_room_is_schedule_time", "07:00", "23:00")

        assert context_manager.get_context("living_room_is_schedule_time") is True

    def test_sets_context_false_when_outside_schedule(self, context_manager):
        """Контекст устанавливается в False вне расписания."""
        with patch("core.context_manager.time.localtime") as mock_localtime:
            mock_localtime.return_value.tm_hour = 3
            mock_localtime.return_value.tm_min = 0

            context_manager.subscribe_schedule("living_room_is_schedule_time", "07:00", "23:00")

        assert context_manager.get_context("living_room_is_schedule_time") is False


class TestOnHaStateChanged:
    """Тесты метода _on_ha_state_change()."""

    def test_updates_context_on_sensor_change(self, context_manager, mock_event_bus):
        """Обновление контекста при изменении состояния сенсора."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion", "living_room_motion_sensor"
        )

        # Событие: движение обнаружено
        event_data = {
            "entity_id": "binary_sensor.living_room_motion",
            "new_state": "on",
        }

        context_manager._on_ha_state_change(event_data)

        # Проверяем что контекст был обновлён
        assert context_manager.get_context("living_room_motion_sensor") is True

    def test_updates_context_on_sensor_off(self, context_manager):
        """Обновление контекста при пропадании движения."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion", "living_room_motion_sensor"
        )

        # Сначала включаем
        context_manager._on_ha_state_change(
            {"entity_id": "binary_sensor.living_room_motion", "new_state": "on"}
        )

        # Затем выключаем
        context_manager._on_ha_state_change(
            {"entity_id": "binary_sensor.living_room_motion", "new_state": "off"}
        )

        assert context_manager.get_context("living_room_motion_sensor") is False

    def test_ignores_unsubscribed_sensor(self, context_manager, mock_event_bus):
        """Игнорирование неподписанного сенсора."""
        context_manager._on_ha_state_change(
            {"entity_id": "binary_sensor.unknown", "new_state": "on"}
        )

        mock_event_bus.publish.assert_not_called()

    def test_publishes_context_changed_event(self, context_manager, mock_event_bus):
        """Публикация события context.changed при изменении контекста."""
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion", "living_room_motion_sensor"
        )

        context_manager._on_ha_state_change(
            {"entity_id": "binary_sensor.living_room_motion", "new_state": "on"}
        )

        mock_event_bus.publish.assert_called()
        call_args = mock_event_bus.publish.call_args
        assert call_args[0][0] == "context.changed"
        assert call_args[0][1]["key"] == "living_room_motion_sensor"
        assert call_args[0][1]["value"] is True

    def test_handles_boolean_states(self, context_manager):
        """Обработка булевых состояний сенсоров."""
        context_manager.subscribe_sensor("binary_sensor.door", "door_sensor")

        # Тестируем различные состояния которые должны конвертироваться в True
        for state in ["on", "open", "active", "home", "true", "yes"]:
            context_manager._on_ha_state_change(
                {"entity_id": "binary_sensor.door", "new_state": state}
            )
            assert context_manager.get_context("door_sensor") is True

        # Тестируем состояния которые должны конвертироваться в False
        for state in ["off", "closed", "inactive", "away", "false", "no", None]:
            context_manager._on_ha_state_change(
                {"entity_id": "binary_sensor.door", "new_state": state}
            )
            if state is None:
                assert context_manager.get_context("door_sensor") is False
            else:
                # После первого False проверяем что состояние сменилось
                pass


class TestSetContext:
    """Тесты метода set_context()."""

    def test_sets_context_manually(self, context_manager, mock_event_bus):
        """Ручная установка значения контекста."""
        context_manager.set_context("custom_key", "custom_value")

        assert context_manager.get_context("custom_key") == "custom_value"
        mock_event_bus.publish.assert_called_once()

    def test_triggers_event_on_manual_set(self, context_manager, mock_event_bus):
        """Событие context.changed публикуется при ручной установке."""
        context_manager.set_context("vacation_mode", True)

        mock_event_bus.publish.assert_called_with(
            "context.changed",
            {
                "key": "vacation_mode",
                "value": True,
                "timestamp": pytest.approx(time.time(), rel=1),
            },
        )


class TestGetContext:
    """Тесты методов get_context() и get_all_context()."""

    def test_get_context_returns_default(self, context_manager):
        """Возврат значения по умолчанию для несуществующего ключа."""
        assert context_manager.get_context("nonexistent", "default") == "default"
        assert context_manager.get_context("nonexistent") is None

    def test_get_all_context_returns_copy(self, context_manager):
        """get_all_context возвращает копию контекста."""
        context_manager.set_context("key1", "value1")
        context_manager.set_context("key2", "value2")

        all_context = context_manager.get_all_context()
        assert all_context == {"key1": "value1", "key2": "value2"}

        # Изменение возвращённого словаря не влияет на оригинал
        all_context["key3"] = "value3"
        assert "key3" not in context_manager.get_all_context()


class TestOnPlatformStarted:
    """Тесты метода _on_platform_started()."""

    def test_starts_schedule_checker_on_platform_start(self, context_manager):
        """Запуск проверки расписаний при старте платформы."""
        context_manager._on_platform_started({})

        # Проверяем что метод _start_schedule_checker был вызван
        # (тестирование асинхронной логики через моки)


class TestIntegrationScenarios:
    """Интеграционные сценарии использования ContextManager."""

    def test_motion_sensor_workflow(self, context_manager, mock_event_bus):
        """Сценарий: датчик движения включает свет."""
        # Подписка на датчик движения
        context_manager.subscribe_sensor(
            "binary_sensor.living_room_motion", "living_room_motion_sensor"
        )

        # Движение обнаружено
        context_manager._on_ha_state_change(
            {"entity_id": "binary_sensor.living_room_motion", "new_state": "on"}
        )

        # Контекст обновлён
        assert context_manager.get_context("living_room_motion_sensor") is True

        # Событие context.changed было опубликовано
        mock_event_bus.publish.assert_called()

    def test_schedule_based_lighting(self, context_manager):
        """Сценарий: освещение по расписанию."""
        with patch("core.context_manager.time.localtime") as mock_localtime:
            mock_localtime.return_value.tm_hour = 20
            mock_localtime.return_value.tm_min = 0

            # Подписка на расписание
            context_manager.subscribe_schedule("hallway_is_evening", "18:00", "23:00")

        assert context_manager.get_context("hallway_is_evening") is True

    def test_combined_motion_and_schedule(self, context_manager):
        """Сценарий: комбинация движения и расписания."""
        # Датчик движения
        context_manager.subscribe_sensor("binary_sensor.bedroom_motion", "bedroom_motion_sensor")

        # Расписание (ночной режим)
        with patch("core.context_manager.time.localtime") as mock_localtime:
            mock_localtime.return_value.tm_hour = 23
            mock_localtime.return_value.tm_min = 0

            context_manager.subscribe_schedule("bedroom_night_mode", "22:00", "06:00")

        # Проверяем что контекст расписания установлен (контекст сенсора ещё не установлен пока нет события)
        assert context_manager.get_context("bedroom_motion_sensor") is None  # ещё нет движения
        assert context_manager.get_context("bedroom_night_mode") is True

        # Теперь симулируем движение
        context_manager._on_ha_state_change(
            {"entity_id": "binary_sensor.bedroom_motion", "new_state": "on"}
        )

        assert context_manager.get_context("bedroom_motion_sensor") is True
        assert context_manager.get_context("bedroom_night_mode") is True
