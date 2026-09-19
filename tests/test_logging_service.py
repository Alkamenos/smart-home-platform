"""Tests for structured logger and logging service."""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import pytest
from src.core.structured_logger import (
    LoggingContext,
    SensitiveDataFilter,
    StructuredFormatter,
    create_structured_logger,
    get_logger,
)
from src.services.logging_service import LogBuffer, LoggingService


class TestStructuredFormatter:
    """Test cases for StructuredFormatter."""

    def test_format_basic_log(self):
        """Test basic log formatting."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "timestamp" in data
        assert data["level"] == "INFO"
        assert data["component"] == "test.logger"
        assert data["message"] == "Test message"

    def test_format_with_location(self):
        """Test formatting with location info."""
        formatter = StructuredFormatter(include_location=True)
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
            func="test_func",
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "location" in data
        assert data["location"]["line"] == 42
        assert data["location"]["file"] == "/test/path.py"

    def test_format_with_exception(self):
        """Test formatting with exception info."""
        formatter = StructuredFormatter()

        try:
            raise RuntimeError("Test error")
        except RuntimeError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="/test/path.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "exception" in data
        assert "RuntimeError" in data["exception"]

    def test_format_without_timestamp(self):
        """Test formatting without timestamp."""
        formatter = StructuredFormatter(include_timestamp=False)
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "timestamp" not in data


class TestSensitiveDataFilter:
    """Test cases for SensitiveDataFilter."""

    def test_mask_token_in_message(self):
        """Test masking token in message."""
        filter_obj = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Using token=secret123 for auth",
            args=(),
            exc_info=None,
        )

        filter_obj.filter(record)

        assert "***REDACTED***" in record.msg
        assert "secret123" not in record.msg

    def test_mask_password_in_args_dict(self):
        """Test masking password in dict args."""
        filter_obj = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Connecting with credentials",
            args={"password": "secret123", "username": "admin"},
            exc_info=None,
        )

        filter_obj.filter(record)

        assert record.args["password"] == "***REDACTED***"
        assert record.args["username"] == "admin"

    def test_mask_api_key_in_message(self):
        """Test masking API key patterns."""
        filter_obj = SensitiveDataFilter()

        test_cases = [
            "api_key=xyz123",
            "apikey: abc789",
            "API_KEY = secret",
        ]

        for test_msg in test_cases:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="/test.py",
                lineno=1,
                msg=test_msg,
                args=(),
                exc_info=None,
            )
            filter_obj.filter(record)
            assert "***REDACTED***" in record.msg

    def test_non_sensitive_data_preserved(self):
        """Test that non-sensitive data is preserved."""
        filter_obj = SensitiveDataFilter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Normal message with no secrets",
            args=(),
            exc_info=None,
        )

        filter_obj.filter(record)

        assert record.msg == "Normal message with no secrets"


class TestLoggingContext:
    """Test cases for LoggingContext."""

    def test_context_adds_extra_fields(self):
        """Test that context adds extra fields to logs."""
        logger = create_structured_logger("test.context", enable_console=False)

        with LoggingContext(logger, entity_id="light.kitchen", user="admin"):
            # Verify context is active
            assert hasattr(logger, "_adapter")

    def test_context_restores_after_exit(self):
        """Test that context is restored after exit."""
        logger = create_structured_logger("test.context2", enable_console=False)

        with LoggingContext(logger, temp_field="value"):
            pass

        # After exit, adapter should be removed
        assert not hasattr(logger, "_adapter")


class TestCreateStructuredLogger:
    """Test cases for create_structured_logger function."""

    def test_create_logger_with_file_handler(self, tmp_path):
        """Test creating logger with file handler."""
        log_file = tmp_path / "test.log"

        logger = create_structured_logger(
            name="test.file_logger",
            log_file=log_file,
            enable_console=False,
        )

        logger.info("Test message")

        # Flush handlers
        for handler in logger.handlers:
            handler.flush()

        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content

    def test_create_logger_with_masking(self):
        """Test creating logger with sensitive data masking."""
        logger = create_structured_logger(
            name="test.mask_logger",
            enable_console=False,
            enable_masking=True,
        )

        # Verify filter is present
        assert any(isinstance(f, SensitiveDataFilter) for f in logger.filters)

    def test_get_logger_returns_existing(self):
        """Test that get_logger returns existing logger."""
        logger1 = get_logger("test.existing")
        logger2 = get_logger("test.existing")

        assert logger1 is logger2


class TestLogBuffer:
    """Test cases for LogBuffer class."""

    @pytest.mark.asyncio
    async def test_add_entry_to_buffer(self):
        """Test adding entry to buffer."""
        buffer = LogBuffer(max_size=10)
        entry = {"timestamp": "2026-09-20T10:00:00Z", "level": "INFO", "message": "Test"}

        await buffer.add(entry)

        entries = await buffer.get_entries(limit=10)
        assert len(entries) == 1
        assert entries[0]["message"] == "Test"

    @pytest.mark.asyncio
    async def test_buffer_respects_max_size(self):
        """Test that buffer respects max size limit."""
        buffer = LogBuffer(max_size=5)

        for i in range(10):
            await buffer.add({"message": f"Entry {i}"})

        entries = await buffer.get_entries(limit=10)
        assert len(entries) == 5
        assert entries[0]["message"] == "Entry 5"

    @pytest.mark.asyncio
    async def test_filter_by_level(self):
        """Test filtering entries by level."""
        buffer = LogBuffer(max_size=100)

        await buffer.add({"level": "INFO", "message": "Info msg"})
        await buffer.add({"level": "ERROR", "message": "Error msg"})
        await buffer.add({"level": "WARNING", "message": "Warning msg"})

        error_entries = await buffer.get_entries(level="ERROR")
        assert len(error_entries) == 1
        assert error_entries[0]["message"] == "Error msg"

    @pytest.mark.asyncio
    async def test_filter_by_component(self):
        """Test filtering entries by component."""
        buffer = LogBuffer(max_size=100)

        await buffer.add({"component": "core.fsm", "message": "FSM msg"})
        await buffer.add({"component": "services.adapter", "message": "Adapter msg"})

        core_entries = await buffer.get_entries(component="core")
        assert len(core_entries) == 1

    @pytest.mark.asyncio
    async def test_subscribe_notification(self):
        """Test subscriber notification on new entry."""
        buffer = LogBuffer(max_size=10)
        received_entries = []

        def callback(entry):
            received_entries.append(entry)

        buffer.subscribe(callback)
        await buffer.add({"message": "Test"})

        assert len(received_entries) == 1
        assert received_entries[0]["message"] == "Test"

    @pytest.mark.asyncio
    async def test_clear_buffer(self):
        """Test clearing buffer."""
        buffer = LogBuffer(max_size=10)

        await buffer.add({"message": "Entry 1"})
        await buffer.add({"message": "Entry 2"})

        await buffer.clear()

        entries = await buffer.get_entries()
        assert len(entries) == 0


class TestLoggingService:
    """Test cases for LoggingService class."""

    def test_initialize_service(self, tmp_path):
        """Test initializing logging service."""
        service = LoggingService(log_dir=tmp_path)

        result = service.initialize(enable_file=True)

        assert result is True
        assert service.is_initialized is True

    def test_get_child_logger(self, tmp_path):
        """Test getting child logger."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=False)

        logger = service.get_logger("test.module")

        assert logger.name == "smart_home.test.module"

    def test_export_logs_json(self, tmp_path):
        """Test exporting logs as JSON."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=False)

        output_file = tmp_path / "export.json"

        # Add some entries to buffer
        asyncio.run(
            service.buffer.add(
                {
                    "timestamp": "2026-09-20T10:00:00Z",
                    "level": "INFO",
                    "component": "test",
                    "message": "Test msg",
                }
            )
        )

        result = service.export_logs(output_file, export_format="json")

        assert result is True
        assert output_file.exists()

        content = json.loads(output_file.read_text())
        assert len(content) > 0

    def test_export_logs_csv(self, tmp_path):
        """Test exporting logs as CSV."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=False)

        output_file = tmp_path / "export.csv"

        asyncio.run(
            service.buffer.add(
                {
                    "timestamp": "2026-09-20T10:00:00Z",
                    "level": "INFO",
                    "component": "test",
                    "message": "Test msg",
                }
            )
        )

        result = service.export_logs(output_file, export_format="csv")

        assert result is True
        assert output_file.exists()

    def test_export_logs_txt(self, tmp_path):
        """Test exporting logs as plain text."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=False)

        output_file = tmp_path / "export.txt"

        asyncio.run(
            service.buffer.add(
                {
                    "timestamp": "2026-09-20T10:00:00Z",
                    "level": "INFO",
                    "component": "test",
                    "message": "Test msg",
                }
            )
        )

        result = service.export_logs(output_file, export_format="txt")

        assert result is True
        assert output_file.exists()

    def test_export_unknown_format(self, tmp_path):
        """Test exporting with unknown format."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=False)

        output_file = tmp_path / "export.xyz"

        result = service.export_logs(output_file, export_format="xyz")

        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_old_logs(self, tmp_path):
        """Test cleaning up old log files."""
        service = LoggingService(log_dir=tmp_path, retention_days=7)

        # Create old log file
        old_log = tmp_path / "old.log"
        old_log.write_text("Old log content")

        # Set modification time to 10 days ago
        old_time = (datetime.now() - timedelta(days=10)).timestamp()
        import os

        os.utime(old_log, (old_time, old_time))

        removed = await service.cleanup_old_logs()

        assert removed >= 1
        assert not old_log.exists()

    def test_stream_logs_subscription(self, tmp_path):
        """Test log streaming subscription."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=False)

        received = []

        def callback(entry):
            received.append(entry)

        # Subscribe and add entry
        service.buffer.subscribe(callback)
        asyncio.run(service.buffer.add({"message": "Stream test"}))

        assert len(received) == 1


class TestIntegration:
    """Integration tests for logging system."""

    def test_full_logging_workflow(self, tmp_path):
        """Test complete logging workflow."""
        # Setup
        service = LoggingService(log_dir=tmp_path)
        service.initialize(level=logging.DEBUG, enable_file=True)

        # Get logger and log messages
        logger = service.get_logger("integration.test")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        # Verify file output
        log_file = tmp_path / "platform.log"
        assert log_file.exists()

        content = log_file.read_text()
        assert "Info message" in content
        assert "Warning message" in content
        assert "Error message" in content

        # Verify buffer has entries
        entries = asyncio.run(service.buffer.get_entries(limit=10))
        assert len(entries) >= 3

    def test_sensitive_data_masked_in_output(self, tmp_path):
        """Test that sensitive data is masked in file output."""
        service = LoggingService(log_dir=tmp_path)
        service.initialize(enable_file=True, enable_masking=True)

        logger = service.get_logger("security.test")
        logger.info("Using token=secret_value for authentication")

        # Flush handlers
        for handler in logger.handlers:
            handler.flush()

        # Check file content
        log_file = tmp_path / "platform.log"
        content = log_file.read_text()

        assert "***REDACTED***" in content
        assert "secret_value" not in content
