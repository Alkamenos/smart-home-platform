"""
Tests for Logger component.

Specification:
1. Logger должен поддерживать уровни логирования: INFO, DEBUG, WARNING, ERROR
2. Каждый лог должен содержать: timestamp, level, component, message, context
3. Logger должен поддерживать вывод в stdout и сохранение в памяти
4. Тихий режим (_quiet) не должен выводить логи в stdout
5. Метод get_logs() должен возвращать все логи или фильтровать по уровню
6. Метод clear() должен очищать историю логов
7. Функция get_logger() должна кэшировать созданные логгеры
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.logger import Logger, get_logger


class TestLoggerInitialization:
    """Тесты инициализации Logger."""

    def test_default_component(self):
        """Logger по умолчанию использует компонент 'platform'."""
        logger = Logger()
        log_entry = logger._format_log("INFO", "test message")
        assert log_entry["component"] == "platform"

    def test_custom_component(self):
        """Logger принимает кастомное имя компонента."""
        logger = Logger(component="fsm")
        log_entry = logger._format_log("INFO", "test message")
        assert log_entry["component"] == "fsm"

    def test_default_output_is_stdout(self):
        """По умолчанию вывод в stdout."""
        logger = Logger()
        assert logger._output == "stdout"

    def test_custom_output(self):
        """Можно задать кастомный вывод."""
        logger = Logger(output="file")
        assert logger._output == "file"

    def test_quiet_mode_enabled(self):
        """Тихий режим отключает вывод в stdout."""
        logger = Logger(quiet=True)
        assert logger._quiet is True

    def test_initial_logs_empty(self):
        """Начальный список логов пуст."""
        logger = Logger()
        assert logger.get_logs() == []


class TestLogFormatting:
    """Тесты форматирования логов."""

    def test_log_contains_timestamp(self):
        """Лог содержит временную метку в ISO формате."""
        from datetime import timezone

        logger = Logger()
        before = datetime.now(timezone.utc)
        log_entry = logger._format_log("INFO", "test")
        after = datetime.now(timezone.utc)

        timestamp = datetime.fromisoformat(log_entry["timestamp"])
        assert before <= timestamp <= after

    def test_log_contains_level(self):
        """Лог содержит уровень логирования."""
        logger = Logger()
        for level in ["INFO", "DEBUG", "WARNING", "ERROR"]:
            log_entry = logger._format_log(level, "test")
            assert log_entry["level"] == level

    def test_log_contains_message(self):
        """Лог содержит сообщение."""
        logger = Logger()
        log_entry = logger._format_log("INFO", "My test message")
        assert log_entry["message"] == "My test message"

    def test_log_contains_context(self):
        """Лог содержит контекст как dict."""
        logger = Logger()
        log_entry = logger._format_log(
            "INFO", "test", entity_id="light.kitchen", extra_data="value"
        )
        assert log_entry["context"] == {"entity_id": "light.kitchen", "extra_data": "value"}

    def test_log_without_context_has_empty_dict(self):
        """Лог без контекста имеет пустой dict."""
        logger = Logger()
        log_entry = logger._format_log("INFO", "test")
        assert log_entry["context"] == {}


class TestLoggingMethods:
    """Тесты методов логирования."""

    def test_info_method_creates_info_log(self):
        """Метод info создаёт лог с уровнем INFO."""
        logger = Logger()
        logger.info("Info message", key="value")
        logs = logger.get_logs()
        assert len(logs) == 1
        assert logs[0]["level"] == "INFO"
        assert logs[0]["message"] == "Info message"
        assert logs[0]["context"] == {"key": "value"}

    def test_debug_method_creates_debug_log(self):
        """Метод debug создаёт лог с уровнем DEBUG."""
        logger = Logger()
        logger.debug("Debug message")
        logs = logger.get_logs()
        assert len(logs) == 1
        assert logs[0]["level"] == "DEBUG"

    def test_warning_method_creates_warning_log(self):
        """Метод warning создаёт лог с уровнем WARNING."""
        logger = Logger()
        logger.warning("Warning message")
        logs = logger.get_logs()
        assert len(logs) == 1
        assert logs[0]["level"] == "WARNING"

    def test_error_method_creates_error_log(self):
        """Метод error создаёт лог с уровнем ERROR."""
        logger = Logger()
        logger.error("Error message", error="details")
        logs = logger.get_logs()
        assert len(logs) == 1
        assert logs[0]["level"] == "ERROR"
        assert logs[0]["context"]["error"] == "details"

    def test_multiple_logs_accumulate(self):
        """Несколько логов накапливаются в списке."""
        logger = Logger()
        logger.info("First")
        logger.debug("Second")
        logger.warning("Third")
        logger.error("Fourth")

        logs = logger.get_logs()
        assert len(logs) == 4
        assert [log["level"] for log in logs] == ["INFO", "DEBUG", "WARNING", "ERROR"]


class TestQuietMode:
    """Тесты тихого режима."""

    @patch("core.logger.print")
    def test_quiet_mode_suppresses_stdout(self, mock_print):
        """В тихом режиме логи не выводятся в stdout."""
        logger = Logger(quiet=True)
        logger.info("Secret message")

        mock_print.assert_not_called()
        # Но логи всё равно сохраняются
        assert len(logger.get_logs()) == 1

    @patch("core.logger.print")
    def test_normal_mode_prints_to_stdout(self, mock_print):
        """В обычном режиме логи выводятся в stdout."""
        logger = Logger(quiet=False)
        logger.info("Public message")

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        log_data = json.loads(call_args)
        assert log_data["message"] == "Public message"


class TestGetLogs:
    """Тесты метода get_logs()."""

    def test_get_all_logs_without_filter(self):
        """get_logs() без параметров возвращает все логи."""
        logger = Logger()
        logger.info("Info")
        logger.debug("Debug")
        logger.warning("Warning")

        all_logs = logger.get_logs()
        assert len(all_logs) == 3

    def test_get_logs_filtered_by_level(self):
        """get_logs(level=...) фильтрует логи по уровню."""
        logger = Logger()
        logger.info("Info 1")
        logger.debug("Debug 1")
        logger.info("Info 2")
        logger.error("Error 1")
        logger.info("Info 3")

        info_logs = logger.get_logs(level="INFO")
        assert len(info_logs) == 3
        assert all(log["level"] == "INFO" for log in info_logs)

        error_logs = logger.get_logs(level="ERROR")
        assert len(error_logs) == 1

        debug_logs = logger.get_logs(level="DEBUG")
        assert len(debug_logs) == 1

    def test_get_logs_nonexistent_level_returns_empty(self):
        """Фильтрация по несуществующему уровню возвращает пустой список."""
        logger = Logger()
        logger.info("Info")

        logs = logger.get_logs(level="CRITICAL")
        assert logs == []


class TestClearMethod:
    """Тесты метода clear()."""

    def test_clear_removes_all_logs(self):
        """clear() удаляет все логи."""
        logger = Logger()
        logger.info("First")
        logger.debug("Second")
        logger.warning("Third")

        assert len(logger.get_logs()) == 3

        logger.clear()

        assert len(logger.get_logs()) == 0

    def test_can_log_after_clear(self):
        """После clear() можно продолжать логирование."""
        logger = Logger()
        logger.info("Before clear")
        logger.clear()
        logger.info("After clear")

        logs = logger.get_logs()
        assert len(logs) == 1
        assert logs[0]["message"] == "After clear"


class TestGetLoggerFunction:
    """Тесты функции get_logger()."""

    def test_get_logger_creates_logger_with_component(self):
        """get_logger() создаёт логгер с указанным компонентом."""
        logger = get_logger("test_component")
        assert logger.name == "platform_v3.test_component"

    def test_get_logger_caches_instances(self):
        """get_logger() кэширует созданные логгеры."""
        logger1 = get_logger("cached_component")
        logger2 = get_logger("cached_component")
        assert logger1 is logger2

    def test_get_logger_different_components_not_cached(self):
        """Логгеры с разными именами не кэшируются вместе."""
        logger1 = get_logger("component_a")
        logger2 = get_logger("component_b")
        assert logger1 is not logger2
        assert logger1.name != logger2.name

    def test_get_logger_default_component(self):
        """get_logger() по умолчанию использует 'platform'."""
        logger = get_logger()
        assert logger.name == "platform_v3.platform"

    def test_get_logger_sets_debug_level(self):
        """get_logger() устанавливает уровень DEBUG."""
        logger = get_logger("test_level")
        assert logger.level == 10  # DEBUG level

    @patch("core.logger.logging.getLogger")
    def test_get_logger_adds_handler_if_needed(self, mock_get_logger):
        """get_logger() добавляет handler если их нет."""
        mock_logger = MagicMock()
        mock_logger.handlers = []  # Нет handlers
        mock_get_logger.return_value = mock_logger

        logger = get_logger("new_component")

        assert mock_logger.addHandler.called

    @patch("core.logger.logging.getLogger")
    def test_get_logger_skips_handler_if_exists(self, mock_get_logger):
        """get_logger() не добавляет handler если он уже есть."""
        mock_logger = MagicMock()
        mock_logger.handlers = [MagicMock()]  # Есть handler
        mock_get_logger.return_value = mock_logger

        logger = get_logger("existing_component")

        assert not mock_logger.addHandler.called


class TestLoggerIntegration:
    """Интеграционные тесты Logger."""

    def test_full_logging_workflow(self):
        """Полный цикл работы с логгером."""
        logger = Logger(component="integration_test", quiet=True)

        # Логирование различных событий
        logger.info("Platform starting", version="1.0")
        logger.debug("Loading configuration", config_path="/path/to/config")
        logger.warning("Deprecated API used", api_name="old_api")
        logger.error("Failed to connect", error="Connection refused")

        # Проверка всех логов
        all_logs = logger.get_logs()
        assert len(all_logs) == 4

        # Проверка фильтрации
        errors = logger.get_logs(level="ERROR")
        assert len(errors) == 1
        assert errors[0]["message"] == "Failed to connect"

        warnings = logger.get_logs(level="WARNING")
        assert len(warnings) == 1

        # Очистка и проверка
        logger.clear()
        assert logger.get_logs() == []

        # Продолжение работы после очистки
        logger.info("Restarted after clear")
        assert len(logger.get_logs()) == 1

    def test_context_preservation_across_levels(self):
        """Контекст сохраняется корректно для разных уровней."""
        logger = Logger(quiet=True)
        common_context = {"entity_id": "light.living_room", "user": "admin"}

        logger.info("User action", **common_context, action="turn_on")
        logger.debug("Detailed state", **common_context, state="ON")
        logger.error("Failure", **common_context, error="timeout")

        logs = logger.get_logs()
        for log in logs:
            assert log["context"]["entity_id"] == "light.living_room"
            assert log["context"]["user"] == "admin"
