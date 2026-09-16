"""Schedule guard for smart home platform.

This module provides a guard function to check if the current time
is within a specified schedule range from behavior params.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from datetime import datetime


def is_within_schedule(ctx: dict) -> bool:
    """Проверяет, находится ли текущее время в пределах schedule из params.

    Args:
        ctx: Контекст, содержащий params с полем schedule в формате "HH:MM-HH:MM".

    Returns:
        bool: True если текущее время в пределах расписания, False иначе.
              Если schedule не указан, возвращает True (всегда активно).

    Examples:
        >>> # schedule: "23:00-07:00" (ночное время)
        >>> # В 12:00 вернет False
        >>> # В 02:00 вернет True
    """
    schedule = ctx.get("params", {}).get("schedule")
    if not schedule:
        return True  # Нет расписания = всегда активно

    # Парсинг "HH:MM-HH:MM"
    start_str, end_str = schedule.split("-")
    now = datetime.now().time()
    start = datetime.strptime(start_str, "%H:%M").time()
    end = datetime.strptime(end_str, "%H:%M").time()

    # Обработка перехода через полночь (23:00-07:00)
    if start <= end:
        return start <= now <= end
    else:
        return now >= start or now <= end
