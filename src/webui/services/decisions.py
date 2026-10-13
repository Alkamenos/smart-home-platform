"""Последнее решение автоматики по устройству (спека 017, US3, FR-018).

Решения движка хранятся по ключу автомата, а интерфейс спрашивает про
устройство. Здесь ключи перебираются (идентификаторы автоматов устройства и его
сущность), и выбирается самое свежее решение: так «почему так» отвечает
человеческим языком и с временем, а не именем константы.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


def decision_view(engine: Any, keys: Iterable[str]) -> dict[str, Any] | None:
    """Собрать последнее решение автоматики по набору ключей.

    Args:
        engine: Движок автоматов (может отсутствовать).
        keys: Ключи, под которыми может быть записано решение: идентификаторы
            автоматов устройства и сущность устройства.

    Returns:
        Словарь с решением (``at``, ``outcome``, ``reason_text``, ``trigger``)
        либо ``None``, если решений не было.
    """
    explain = getattr(engine, "explain", None)
    if not callable(explain):
        return None

    best: Any = None
    for key in keys:
        if not key:
            continue
        decision = explain(key)
        if decision is not None and (best is None or decision.at > best.at):
            best = decision

    if best is None:
        return None

    return {
        "at": datetime.fromtimestamp(best.at, tz=UTC).isoformat(),
        "outcome": best.outcome,
        "reason_code": best.reason_code,
        "reason_text": best.reason_text,
        "trigger": best.trigger,
    }
