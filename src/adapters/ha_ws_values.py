"""Value helpers for the Home Assistant WebSocket client (spec 018, T059)."""

from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    """Значение приводится к числу.

    Args:
        value: Что проверить.

    Returns:
        True, если это число или числовая строка.
    """
    try:
        float(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def _as_float(value: Any) -> float | None:
    """Привести к числу или вернуть None.

    Args:
        value: Что привести.

    Returns:
        Число либо None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
