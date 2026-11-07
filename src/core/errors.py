"""Классы отказов платформы (спека 018, D5).

Три класса различаются по смыслу, а не по месту возникновения:

* ожидаемое состояние — данных нет, прибор недоступен, ручной оверрайд;
* дефект — непредвиденное исключение, которое нельзя маскировать под «нет данных»;
* авария — нарушение правила безопасности, требующее отдельного канала.

Модуль намеренно не зависит от FastAPI и адаптеров: это доменное понятие.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations


class PlatformError(Exception):
    """Базовая ошибка платформы с машинным кодом.

    Args:
        message: Человеческое объяснение.
        code: Машинный код; по умолчанию — код класса.
    """

    code = "platform_error"
    is_fault = False
    http_status = 500

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, str]:
        """Представить ошибку для журнала или ответа.

        Returns:
            Словарь с кодом и сообщением.
        """
        return {"code": self.code, "message": self.message}


class ExpectedConditionError(PlatformError):
    """Ожидаемое состояние: решение не принято, но поломки нет.

    Примеры: датчик молчит, прибор недоступен, действует ручная блокировка.
    Это не дефект и не повод для тревоги уровня «вмешаться».
    """

    code = "expected_condition"
    is_fault = False
    http_status = 400


class DomainDefectError(PlatformError):
    """Непредвиденная ошибка в коде: должна быть видна как дефект."""

    code = "internal_error"
    is_fault = True


class SafetyViolationError(PlatformError):
    """Нарушено правило безопасности: отдельный канал и приоритет."""

    code = "safety_violation"
    is_fault = True
    http_status = 409
