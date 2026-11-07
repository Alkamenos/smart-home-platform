"""JSON-режим структурных логов (спека 018, US5, T066)."""

from __future__ import annotations

import json
import logging

from core.structured_logger import StructuredFormatter


def test_json_log_contains_trace_id() -> None:
    """JSON-запись несёт уровень, компонент, сообщение и trace_id."""
    record = logging.LogRecord(
        name="platform.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="проверка",
        args=(),
        exc_info=None,
    )
    record.trace_id = "abc123"

    payload = json.loads(StructuredFormatter(colored=False).format(record))

    assert payload["level"] == "WARNING"
    assert payload["component"] == "platform.test"
    assert payload["message"] == "проверка"
    assert payload["context"]["trace_id"] == "abc123"
