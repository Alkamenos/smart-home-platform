"""
Structured Logger for Smart Home Platform.

Provides structured JSON logging with context enrichment,
sensitive data masking, and multiple output handlers.
"""

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.

    Converts log records to JSON format with enriched context.
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_level: bool = True,
        include_location: bool = False,
    ):
        """
        Initialize the structured formatter.

        Args:
            include_timestamp: Include ISO timestamp in output.
            include_level: Include log level in output.
            include_location: Include file/line location (verbose).
        """
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_level = include_level
        self.include_location = include_location

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON string.

        Args:
            record: Log record to format.

        Returns:
            JSON-formatted log entry.
        """
        log_data: dict[str, Any] = {}

        # Add timestamp
        if self.include_timestamp:
            log_data["timestamp"] = datetime.fromtimestamp(record.created, tz=UTC).isoformat()

        # Add level
        if self.include_level:
            log_data["level"] = record.levelname

        # Add component (logger name)
        log_data["component"] = record.name

        # Add message
        log_data["message"] = record.getMessage()

        # Add location info if enabled
        if self.include_location:
            log_data["location"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra context from record
        extra_context = self._extract_extra_context(record)
        if extra_context:
            log_data["context"] = extra_context

        return json.dumps(log_data, default=str, ensure_ascii=False)

    def _extract_extra_context(self, record: logging.LogRecord) -> dict[str, Any]:
        """
        Extract extra context from log record.

        Args:
            record: Log record with potential extra attributes.

        Returns:
            Dictionary of extra context.
        """
        skip_keys = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
        }

        context = {}
        for key, value in record.__dict__.items():
            if key not in skip_keys:
                context[key] = value

        return context


class SensitiveDataFilter(logging.Filter):
    """
    Filter that masks sensitive data in log messages.

    Prevents accidental logging of tokens, passwords, and secrets.
    """

    SENSITIVE_PATTERNS = [
        "token",
        "password",
        "secret",
        "api_key",
        "apikey",
        "auth",
        "credential",
        "private_key",
    ]

    MASK_VALUE = "***REDACTED***"

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter log record, masking sensitive data.

        Args:
            record: Log record to filter.

        Returns:
            True to allow record to be logged.
        """
        # Mask sensitive fields in message
        record.msg = self._mask_sensitive_data(str(record.msg))

        # Mask sensitive fields in args
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = {k: self._mask_if_sensitive(k, v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._mask_if_sensitive(f"arg_{i}", v) for i, v in enumerate(record.args)
                )

        # Mask sensitive extra attributes
        for attr in dir(record):
            if not attr.startswith("_") and attr.lower() in self.SENSITIVE_PATTERNS:
                setattr(record, attr, self.MASK_VALUE)

        return True

    def _mask_sensitive_data(self, message: str) -> str:
        """
        Mask sensitive patterns in message.

        Args:
            message: Log message string.

        Returns:
            Message with sensitive data masked.
        """
        # Simple masking - replace values after common separators
        for pattern in self.SENSITIVE_PATTERNS:
            # Mask patterns like "token=xyz" or "token: xyz"
            message = self._mask_pattern(message, pattern)

        return message

    def _mask_pattern(self, text: str, pattern: str) -> str:
        """
        Mask specific pattern in text.

        Args:
            text: Text to process.
            pattern: Pattern to look for.

        Returns:
            Text with pattern values masked.
        """
        import re

        # Match pattern followed by = or : and a value
        regex = rf"({pattern}\s*[=:]\s*)(\S+)"

        def replacer(match: re.Match) -> str:
            return match.group(1) + self.MASK_VALUE

        return re.sub(regex, replacer, text, flags=re.IGNORECASE)

    def _mask_if_sensitive(self, key: str, value: Any) -> Any:
        """
        Mask value if key suggests it's sensitive.

        Args:
            key: Attribute name.
            value: Attribute value.

        Returns:
            Masked or original value.
        """
        key_lower = key.lower()
        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in key_lower:
                return self.MASK_VALUE
        return value


def create_structured_logger(
    name: str,
    level: int = logging.INFO,
    log_file: Path | None = None,
    enable_console: bool = True,
    enable_masking: bool = True,
    include_location: bool = False,
) -> logging.Logger:
    """
    Create a configured structured logger.

    Args:
        name: Logger name (typically __name__).
        level: Logging level.
        log_file: Optional file path for file handler.
        enable_console: Enable console output.
        enable_masking: Enable sensitive data masking.
        include_location: Include file/line in logs (verbose).

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Clear existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create formatter
    formatter = StructuredFormatter(
        include_timestamp=True,
        include_level=True,
        include_location=include_location,
    )

    # Add sensitive data filter
    if enable_masking:
        logger.addFilter(SensitiveDataFilter())

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler
    if log_file:
        # Ensure directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


class LoggingContext:
    """
    Context manager for adding temporary context to log messages.

    Usage:
        with LoggingContext(logger, entity_id="light.kitchen"):
            logger.info("Processing entity")
    """

    def __init__(self, logger: logging.Logger, **context: Any):
        """
        Initialize logging context.

        Args:
            logger: Target logger.
            **context: Context variables to add.
        """
        self.logger = logger
        self.context = context
        self.old_adapter: logging.LoggerAdapter | None = None

    def __enter__(self) -> logging.LoggerAdapter:
        """Enter context, return adapter with context."""
        adapter = logging.LoggerAdapter(self.logger, self.context)
        self.old_adapter = getattr(self.logger, "_adapter", None)
        self.logger._adapter = adapter  # type: ignore[attr-defined]
        return adapter

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context, restore previous state."""
        if hasattr(self.logger, "_adapter"):
            delattr(self.logger, "_adapter")


def get_logger(name: str) -> logging.Logger:
    """
    Get or create a logger with default structured configuration.

    Args:
        name: Logger name.

    Returns:
        Configured logger instance.
    """
    # Check if logger already exists with handlers
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    # Create new structured logger
    return create_structured_logger(
        name=name,
        level=logging.INFO,
        enable_console=True,
        enable_masking=True,
    )
