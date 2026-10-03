"""
Скрипт проверки безопасности токенов и чувствительных данных в Smart Home Platform.

Проверяет:
1. Что токены не логируются в открытом виде
2. Что токены не содержатся в сообщениях об ошибках
3. Что токены шифруются при сохранении
4. Что токены маскируются в сообщениях об ошибках (показываются только первые 8 символов)
5. Что исключительные ситуации не раскрывают чувствительные данные
"""

import json
import re
from typing import Any

import pytest  # noqa: F401 — используется в блоке __main__


class SecurityAnalyzer:
    """Анализатор логов для проверки безопасности токенов."""

    # Паттерны для поиска токенов (часто начинаются с eyJ для JWT)
    TOKEN_PATTERNS = [
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",  # JWT tokens
        r"Bearer\s+([A-Za-z0-9_-]{40,})",  # Bearer tokens
        r"api_key[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]{20,})[\"']?",  # API keys
        r"token[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_-]{20,})[\"']?",  # Tokens
    ]

    # Паттерны для поиска обычных чувствительных данных
    SENSITIVE_PATTERNS = [
        "password",
        "secret",
        "api_key",
        "apikey",
        "auth",
        "credential",
        "access_token",
        "refresh_token",
    ]

    def __init__(self, log_content: str):
        """Инициализирует анализатор с содержимым логов.

        Args:
            log_content: Содержимое log файла
        """
        self.log_content = log_content
        self.logs = self._parse_logs()

    def _parse_logs(self) -> list[dict[str, Any]]:
        """Парсит JSON логи из содержимого файла.

        Returns:
            Список распарсенных логов
        """
        logs = []
        for line in self.log_content.strip().split("\n"):
            if line.strip():
                try:
                    log_entry = json.loads(line)
                    logs.append(log_entry)
                except json.JSONDecodeError:
                    # Пропускаем non-JSON логи
                    pass
        return logs

    def _find_tokens_in_text(self, text: str) -> list[str]:
        """Находит потенциальные токены в тексте.

        Args:
            text: Текст для анализа

        Returns:
            Список найденных токенов
        """
        found_tokens = []
        for pattern in self.TOKEN_PATTERNS:
            matches = re.findall(pattern, text)
            found_tokens.extend(matches)
        return found_tokens

    def check_no_plaintext_tokens(self) -> tuple[bool, str]:
        """Проверяет что токены не логируются в открытом виде.

        Returns:
            (is_valid, message)
        """
        found_tokens = []

        for i, log in enumerate(self.logs):
            message = log.get("message", "")
            context = log.get("context", {})

            # Проверяем message
            tokens = self._find_tokens_in_text(message)
            if tokens:
                found_tokens.append((i, "message", tokens))

            # Проверяем context рекурсивно
            context_str = json.dumps(context)
            tokens = self._find_tokens_in_text(context_str)
            if tokens:
                found_tokens.append((i, "context", tokens))

        if found_tokens:
            error_msg = "Найдены открытые токены в логах:\n"
            for log_idx, field, tokens in found_tokens:
                error_msg += f"  Лог {log_idx} ({field}): {len(tokens)} токен(ов)\n"
            return False, error_msg

        return True, "Открытые токены не найдены в логах"

    def check_sensitive_fields_masked(self) -> tuple[bool, str]:
        """Проверяет что чувствительные поля маскируются.

        Returns:
            (is_valid, message)
        """
        masked_pattern = re.compile(r"\*{3}REDACTED\*{3}|^\S{0,8}$")

        for log in self.logs:
            context = log.get("context", {})

            for key, value in context.items():
                key_lower = key.lower()

                # Проверяем if ключ похож на чувствительный
                is_sensitive = any(sp in key_lower for sp in self.SENSITIVE_PATTERNS)

                if (
                    is_sensitive
                    and isinstance(value, str)
                    and len(value) > 0
                    and not (masked_pattern.match(value) or len(value) <= 8)
                ):
                    return False, (f"Чувствительное поле '{key}' не маскировано: '{value[:20]}...'")

        return True, "Чувствительные поля маскированы правильно"

    def check_error_messages_safe(self) -> tuple[bool, str]:
        """Проверяет что сообщения об ошибках не содержат токены.

        Returns:
            (is_valid, message)
        """
        error_logs = [log for log in self.logs if log.get("level") == "ERROR"]

        for log in error_logs:
            message = log.get("message", "")
            context = log.get("context", {})
            error_message = context.get("error_message", "")

            # Проверяем что нет открытых токенов
            for text in [message, error_message]:
                tokens = self._find_tokens_in_text(text)
                if tokens:
                    return False, (f"Найдены токены в сообщении об ошибке: {text[:100]}...")

        return True, f"Проверено {len(error_logs)} сообщений об ошибках - токены не найдены"

    def check_exception_safety(self) -> tuple[bool, str]:
        """Проверяет что исключения не содержат токены.

        Returns:
            (is_valid, message)
        """
        for log in self.logs:
            if "exception" in log:
                exception_text = log["exception"]

                # Проверяем что нет открытых токенов в stacktrace
                tokens = self._find_tokens_in_text(exception_text)
                if tokens:
                    return False, (f"Найдены токены в исключении: {exception_text[:100]}...")

        return True, "Исключения проверены - токены не найдены"

    def generate_report(self) -> str:
        """Генерирует отчет о проверке безопасности.

        Returns:
            Форматированный отчет
        """
        report_lines = [
            "=" * 80,
            "ОТЧЕТ О ПРОВЕРКЕ БЕЗОПАСНОСТИ",
            "=" * 80,
            "",
        ]

        # Статистика
        error_count = len(
            [log_entry for log_entry in self.logs if log_entry.get("level") == "ERROR"]
        )
        report_lines.extend(
            [
                f"Всего логов: {len(self.logs)}",
                f"Логов об ошибках: {error_count}",
                "",
            ]
        )

        # Результаты проверок
        checks = [
            ("Отсутствие открытых токенов", self.check_no_plaintext_tokens()),
            ("Маскирование чувствительных полей", self.check_sensitive_fields_masked()),
            ("Безопасность сообщений об ошибках", self.check_error_messages_safe()),
            ("Безопасность исключений", self.check_exception_safety()),
        ]

        report_lines.append("РЕЗУЛЬТАТЫ ПРОВЕРОК БЕЗОПАСНОСТИ:")
        report_lines.append("-" * 80)

        all_passed = True
        for check_name, (is_valid, message) in checks:
            status = "✓ PASSED" if is_valid else "✗ FAILED"
            report_lines.append(f"{status}: {check_name}")
            report_lines.append(f"  {message}")
            if not is_valid:
                all_passed = False

        report_lines.extend(
            [
                "",
                "=" * 80,
                f"ИТОГО: {'ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ' if all_passed else 'ОБНАРУЖЕНЫ ПРОБЛЕМЫ БЕЗОПАСНОСТИ'}",
                "=" * 80,
            ]
        )

        return "\n".join(report_lines)


# Тесты вынесены в tests/security/test_log_security.py (спека 009, T011a).
# Прежние 6 проверок жили здесь и выполнялись только при явном указании пути:
# pytest не собирает файл, потому что его имя не матчит `test_*.py`. То есть
# проверки безопасности токенов в логах не происходили ни в одном обычном
# прогоне.
#
# При переносе добавлена обратная сторона каждой проверки: анализатор,
# который всегда возвращал бы True, прошёл бы и прежние тесты.


# Тесты перенесены в собираемые pytest файлы (спека 009):
#
# - шифрование токенов → `tests/unit/core/test_encryption.py` (T010)
# - проверки безопасности логов → `tests/security/test_log_security.py` (T011a)
#
# Здесь остаётся сам `SecurityAnalyzer` — он нужен как скрипт ручной проверки
# журналов. Файл не собирается pytest: имя не начинается с `test_`. Именно этим
# свойством были скрыты обе группы тестов — они выполнялись только при явном
# указании пути и никогда в обычном прогоне.


if __name__ == "__main__":
    # Запуск тестов и генерация отчета
    pytest.main([__file__, "-v", "--tb=short"])
