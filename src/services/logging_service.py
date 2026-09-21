"""
Logging Service for Smart Home Platform.

Centralized logging service with multiple output handlers,
log rotation, and WebSocket streaming support.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Import ColoredConsoleHandler and StructuredFormatter for use in logging_service
from core.structured_logger import (
    ColoredConsoleHandler,
    SensitiveDataFilter,
    StructuredFormatter,
)


logger = logging.getLogger(__name__)


class LogBuffer:
    """
    In-memory circular buffer for recent log entries.

    Used for WebSocket streaming and real-time viewing.
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialize log buffer.

        Args:
            max_size: Maximum number of entries to keep.
        """
        self.max_size = max_size
        self._buffer: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []

    async def add(self, entry: dict[str, Any]) -> None:
        """
        Add log entry to buffer.

        Args:
            entry: Log entry dictionary.
        """
        async with self._lock:
            self._buffer.append(entry)

            # Trim buffer if exceeds max size
            if len(self._buffer) > self.max_size:
                self._buffer = self._buffer[-self.max_size :]

            # Notify subscribers
            for callback in self._subscribers:
                try:
                    callback(entry)
                except RuntimeError as e:
                    logger.error(f"Error notifying subscriber: {e}")

    async def get_entries(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        level: str | None = None,
        component: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get filtered log entries.

        Args:
            start_time: Filter entries after this time.
            end_time: Filter entries before this time.
            level: Filter by log level.
            component: Filter by component name.
            limit: Maximum entries to return.

        Returns:
            List of filtered log entries.
        """
        async with self._lock:
            result = self._buffer.copy()

        # Apply filters
        if start_time:
            result = [e for e in result if e.get("timestamp", "") >= start_time.isoformat()]

        if end_time:
            result = [e for e in result if e.get("timestamp", "") <= end_time.isoformat()]

        if level:
            result = [e for e in result if e.get("level") == level]

        if component:
            result = [e for e in result if e.get("component", "").startswith(component)]

        # Apply limit
        return result[-limit:]

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """
        Subscribe to new log entries.

        Args:
            callback: Function to call on new entry.
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """
        Unsubscribe from log updates.

        Args:
            callback: Callback function to remove.
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def clear(self) -> None:
        """Clear all entries from buffer."""
        async with self._lock:
            self._buffer.clear()


class BufferingHandler(logging.Handler):
    """
    Custom logging handler that sends log records to LogBuffer.

    Enables real-time streaming of log entries.
    """

    def __init__(self, buffer: LogBuffer):
        """
        Initialize buffering handler.

        Args:
            buffer: LogBuffer instance to send entries to.
        """
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record to the buffer.

        Args:
            record: Log record to emit.
        """
        try:
            # Format the record using the formatter
            log_entry_str = self.format(record)

            # Parse back to dict for buffer (since our formatter outputs JSON)
            import json

            try:
                log_entry = json.loads(log_entry_str)
            except json.JSONDecodeError:
                log_entry = {
                    "message": log_entry_str,
                    "level": record.levelname,
                    "component": record.name,
                }

            # Try to schedule buffer add asynchronously
            # Use run_coroutine_threadsafe if we're in a thread with an event loop
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self.buffer.add(log_entry))
            except RuntimeError:
                # No running event loop, add synchronously
                # Create a new event loop if needed
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self.buffer.add(log_entry))
                    loop.close()
                except RuntimeError as e2:
                    logger.debug(f"Could not add to buffer: {e2}")
        except RuntimeError as e:
            # Ignore errors during shutdown
            if "event loop is closed" not in str(e).lower():
                logger.debug(f"Error in BufferingHandler: {e}")


class LoggingService:
    """
    Central logging service for the platform.

    Features:
    - Multiple output handlers (file, console, HA API, WebSocket)
    - Log rotation and retention
    - Real-time streaming via WebSocket
    - Filtering and search capabilities
    """

    def __init__(
        self,
        log_dir: Path | None = None,
        retention_days: int = 7,
        max_buffer_size: int = 1000,
    ):
        """
        Initialize logging service.

        Args:
            log_dir: Directory for log files.
            retention_days: Days to retain old logs.
            max_buffer_size: Max entries in memory buffer.
        """
        self.log_dir = log_dir or Path("/var/log/smart-home")
        self.retention_days = retention_days
        self.buffer = LogBuffer(max_size=max_buffer_size)
        self._root_logger: logging.Logger | None = None
        self._handlers: list[logging.Handler] = []
        self._initialized = False

    def initialize(
        self,
        level: int = logging.INFO,
        enable_console: bool = True,
        enable_file: bool = True,
        enable_masking: bool = True,
        colored_console: bool = True,
    ) -> bool:
        """
        Initialize the logging service.

        Args:
            level: Root logging level.
            enable_console: Enable console output.
            enable_file: Enable file output.
            enable_masking: Enable sensitive data masking.
            colored_console: Enable colored console output.

        Returns:
            True if initialization successful.
        """
        try:
            logger.info("Initializing LoggingService...")

            # Create log directory
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # Configure root logger
            self._root_logger = logging.getLogger("smart_home")
            self._root_logger.setLevel(level)

            # Clear existing handlers
            self._root_logger.handlers.clear()

            # Add sensitive data filter
            if enable_masking:
                sensitive_filter = SensitiveDataFilter()
                self._root_logger.addFilter(sensitive_filter)

            # Console handler
            if enable_console:
                if colored_console:
                    # Use colored console handler with human-readable format
                    console_handler = ColoredConsoleHandler()
                    console_formatter = StructuredFormatter(
                        include_timestamp=True,
                        include_level=True,
                        include_location=False,
                        colored=True,
                    )
                else:
                    # Use standard handler with JSON format
                    console_handler = logging.StreamHandler()
                    console_formatter = StructuredFormatter(
                        include_timestamp=True,
                        include_level=True,
                        include_location=False,
                        colored=False,
                    )

                console_handler.setLevel(level)
                console_handler.setFormatter(console_formatter)
                if enable_masking:
                    console_handler.addFilter(sensitive_filter)
                self._root_logger.addHandler(console_handler)
                self._handlers.append(console_handler)

            # File handler (always JSON format for parsing)
            if enable_file:
                log_file = self.log_dir / "platform.log"
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setLevel(level)
                file_formatter = StructuredFormatter(
                    include_timestamp=True,
                    include_level=True,
                    include_location=False,
                    colored=False,  # Files always use JSON
                )
                file_handler.setFormatter(file_formatter)
                if enable_masking:
                    file_handler.addFilter(sensitive_filter)
                self._root_logger.addHandler(file_handler)
                self._handlers.append(file_handler)

            # Buffering handler for real-time streaming (JSON format)
            buffer_handler = BufferingHandler(self.buffer)
            buffer_handler.setLevel(level)
            buffer_formatter = StructuredFormatter(
                include_timestamp=True,
                include_level=True,
                include_location=False,
                colored=False,
            )
            buffer_handler.setFormatter(buffer_formatter)
            if enable_masking:
                buffer_handler.addFilter(sensitive_filter)
            self._root_logger.addHandler(buffer_handler)
            self._handlers.append(buffer_handler)

            # Prevent propagation
            self._root_logger.propagate = False

            self._initialized = True
            logger.info("LoggingService initialized successfully")
            return True

        except RuntimeError as e:
            logger.error(f"Failed to initialize LoggingService: {e}")
            return False

    def get_logger(self, name: str, level: int | None = None) -> logging.Logger:
        """
        Get a child logger.

        Args:
            name: Logger name (typically module __name__).
            level: Optional custom level.

        Returns:
            Configured logger instance.
        """
        child_logger = logging.getLogger(f"smart_home.{name}")

        if level:
            child_logger.setLevel(level)

        return child_logger

    async def stream_logs(
        self,
        callback: Callable[[dict[str, Any]], None],
        duration: timedelta | None = None,
    ) -> None:
        """
        Stream logs to callback function.

        Args:
            callback: Function to receive log entries.
            duration: Optional streaming duration.
        """
        self.buffer.subscribe(callback)

        if duration:
            await asyncio.sleep(duration.total_seconds())
            self.buffer.unsubscribe(callback)

    async def cleanup_old_logs(self) -> int:
        """
        Remove log files older than retention period.

        Returns:
            Number of files removed.
        """
        removed_count = 0
        cutoff = datetime.now() - timedelta(days=self.retention_days)

        try:
            for log_file in self.log_dir.glob("*.log*"):
                try:
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if mtime < cutoff:
                        log_file.unlink()
                        removed_count += 1
                        logger.info(f"Removed old log file: {log_file}")
                except RuntimeError as e:
                    logger.warning(f"Error processing log file {log_file}: {e}")
        except RuntimeError as e:
            logger.error(f"Error during log cleanup: {e}")

        return removed_count

    def export_logs(
        self,
        output_path: Path,
        export_format: str = "json",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        level: str | None = None,
    ) -> bool:
        """
        Export logs to file.

        Args:
            output_path: Output file path.
            export_format: Export format (json, csv, txt).
            start_time: Filter start time.
            end_time: Filter end time.
            level: Filter by level.

        Returns:
            True if export successful.
        """
        try:
            # Get filtered entries
            entries = asyncio.run(
                self.buffer.get_entries(
                    start_time=start_time,
                    end_time=end_time,
                    level=level,
                    limit=10000,
                )
            )

            # Export based on format
            if export_format.lower() == "json":
                self._export_json(output_path, entries)
            elif export_format.lower() == "csv":
                self._export_csv(output_path, entries)
            elif export_format.lower() == "txt":
                self._export_txt(output_path, entries)
            else:
                logger.error(f"Unknown export format: {export_format}")
                return False

            logger.info(f"Exported {len(entries)} logs to {output_path}")
            return True

        except RuntimeError as e:
            logger.error(f"Failed to export logs: {e}")
            return False

    def _export_json(self, path: Path, entries: list[dict[str, Any]]) -> None:
        """Export logs as JSON."""
        import json

        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)

    def _export_csv(self, path: Path, entries: list[dict[str, Any]]) -> None:
        """Export logs as CSV."""
        import csv

        if not entries:
            return

        fieldnames = ["timestamp", "level", "component", "message"]

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(entries)

    def _export_txt(self, path: Path, entries: list[dict[str, Any]]) -> None:
        """Export logs as plain text."""
        with open(path, "w", encoding="utf-8") as f:
            for entry in entries:
                timestamp = entry.get("timestamp", "")
                level = entry.get("level", "")
                component = entry.get("component", "")
                message = entry.get("message", "")
                f.write(f"[{timestamp}] [{level}] [{component}] {message}\n")

    @property
    def is_initialized(self) -> bool:
        """Check if service is initialized."""
        return self._initialized


# Global logging service instance
_logging_service: LoggingService | None = None


def get_logging_service() -> LoggingService:
    """Get or create global logging service instance."""
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService()
    return _logging_service


def setup_platform_logging(
    log_dir: Path | None = None,
    level: int = logging.INFO,
    enable_masking: bool = True,
) -> LoggingService:
    """
    Setup platform-wide logging configuration.

    Args:
        log_dir: Directory for log files.
        level: Root logging level.
        enable_masking: Enable sensitive data masking.

    Returns:
        Initialized logging service.
    """
    service = get_logging_service()
    service.initialize(
        log_dir=log_dir,
        level=level,
        enable_masking=enable_masking,
    )
    return service
