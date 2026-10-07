"""Управляемое время для проверок блокировки.

Подмена системных часов здесь не применяется: блокировка считается по времени
настенному, и подмена `time.time` разошлась бы с тем, что сохраняется в факте
ручного действия. Вместо этого время выдаётся явно, и проверка управляет им сама.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


__all__ = ["FrozenClock"]


class FrozenClock:
    """Часы, которые двигает только владелец.

    Использование: счётчик времени идёт через объект, а не через модуль, поэтому
    проверка не подменяет ничего глобального и не влияет на соседние тесты.
    """

    def __init__(self, start: datetime | None = None) -> None:
        """Создать часы.

        Args:
            start: Начальный момент; по умолчанию — текущее время UTC без
                часового пояса, как его хранит модель факта ручного действия.
        """
        self._now = start or datetime.now(UTC).replace(tzinfo=None)

    def now(self) -> datetime:
        """Текущий момент.

        Returns:
            Наивное время UTC.
        """
        return self._now

    def advance(self, minutes: float) -> None:
        """Продвинуть часы.

        Args:
            minutes: Сколько минут прибавить.
        """
        self._now = self._now + timedelta(minutes=minutes)
