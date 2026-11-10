"""Ожидание применения команды прибором.

Home Assistant подтверждает вызов сервиса, но это не значит, что прибор
изменил состояние: Zigbee-устройство может не ответить, штора — не доехать,
лампа — остаться выключенной. Диспетчер запоминает, чего ждал, а обход дома
сверяет ожидание с фактом через несколько минут.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


#: Сервис → ожидаемое устойчивое состояние прибора.
SERVICE_STATES: dict[str, str] = {
    "turn_on": "on",
    "turn_off": "off",
    "open_cover": "open",
    "close_cover": "closed",
}

#: Состояния, которые ещё не являются провалом: прибор в процессе.
TRANSITIONAL_STATES = frozenset({"opening", "closing", "unavailable", "unknown"})

#: Сколько секунд хранить ожидание, если обход не успел его проверить.
DEFAULT_TTL_SEC = 15 * 60

#: Допуск по умолчанию: через сколько минут сообщать о неприменённой команде.
DEFAULT_GRACE_MIN = 5.0


@dataclass(frozen=True)
class CommandExpectation:
    """Чего платформа ждала от прибора после команды.

    Attributes:
        device_id: Прибор.
        domain: Домен команды.
        service: Сервис команды.
        expected_state: Ожидаемое состояние (``on``/``off``/``open``/``closed``).
        sent_at: Время отправки (Unix).
    """

    device_id: str
    domain: str
    service: str
    expected_state: str
    sent_at: float

    def age_sec(self, now: float) -> float:
        """Сколько секунд прошло с отправки.

        Args:
            now: Текущее время Unix.

        Returns:
            Возраст ожидания.
        """
        return max(0.0, now - self.sent_at)


class CommandExpectationTracker:
    """Хранить ожидания применения команд.

    Args:
        clock: Источник времени; подменяется в тестах.
        ttl_sec: Сколько хранить ожидание до принудительной очистки.
    """

    def __init__(self, clock: Callable[[], float] | None = None, ttl_sec: float = DEFAULT_TTL_SEC):
        self._clock = clock or time.time
        self._ttl_sec = max(60.0, float(ttl_sec))
        self._pending: dict[str, CommandExpectation] = {}

    def record(self, device_id: str, domain: str, service: str) -> CommandExpectation | None:
        """Запомнить ожидание, если команда меняет состояние прибора.

        Args:
            device_id: Прибор.
            domain: Домен команды.
            service: Сервис команды.

        Returns:
            Созданное ожидание либо ``None`` для команд без состояния
            (``number.set_value``, ``input_text.set_value`` и подобных).
        """
        expected = SERVICE_STATES.get(service)
        if expected is None:
            return None
        expectation = CommandExpectation(
            device_id=device_id,
            domain=domain,
            service=service,
            expected_state=expected,
            sent_at=self._clock(),
        )
        self._pending[device_id] = expectation
        return expectation

    def clear(self, device_id: str) -> None:
        """Забыть ожидание по прибору.

        Args:
            device_id: Прибор.

        Returns:
            Ничего.
        """
        self._pending.pop(device_id, None)

    def pending(self, now: float | None = None) -> tuple[CommandExpectation, ...]:
        """Ожидания, которые ещё имеют смысл.

        Args:
            now: Текущее время; по умолчанию системное.

        Returns:
            Кортеж ожиданий; просроченные удаляются.
        """
        moment = self._clock() if now is None else now
        expired = [
            device_id
            for device_id, expectation in self._pending.items()
            if expectation.age_sec(moment) > self._ttl_sec
        ]
        for device_id in expired:
            self._pending.pop(device_id, None)
        return tuple(self._pending.values())

    def is_applied(self, expectation: CommandExpectation, actual: str | None) -> bool:
        """Совпало ли фактическое состояние с ожиданием.

        Args:
            expectation: Ожидание.
            actual: Фактическое состояние прибора.

        Returns:
            True, если команда применена.
        """
        value = str(actual or "").strip().lower()
        if not value:
            return False
        return value == expectation.expected_state

    def is_transitional(self, actual: str | None) -> bool:
        """Идёт ли ещё переход, который не считается провалом.

        Args:
            actual: Фактическое состояние.

        Returns:
            True для ``opening``/``closing``/``unavailable``/``unknown``.
        """
        return str(actual or "").strip().lower() in TRANSITIONAL_STATES

    def problem(
        self,
        expectation: CommandExpectation,
        *,
        actual: str | None,
        area: str,
        name: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Собрать проблему «команда не применена».

        Args:
            expectation: Ожидание.
            actual: Фактическое состояние.
            area: Место прибора.
            name: Имя прибора.
            now: Текущее время.

        Returns:
            Словарь проблемы в форме обхода.
        """
        moment = self._clock() if now is None else now
        minutes = expectation.age_sec(moment) / 60.0
        return {
            "kind": "command_not_applied",
            "subject": expectation.device_id,
            "name": name or expectation.device_id,
            "area": area,
            "detail": (
                f"{name or expectation.device_id} ({area or 'без места'}): "
                f"команда {expectation.service} не применена за {minutes:.0f} мин, "
                f"прибор в состоянии {actual!r}"
            ),
            "value": actual,
            "source": "command",
            "at": None,
        }
