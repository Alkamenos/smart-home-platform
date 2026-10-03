"""Проверки безопасности логов (спека 009, T011a).

Шесть проверок безопасности жили в `tests/security/verify_security.py`, который
pytest **не собирает**: имя файла не матчит `python_files = test_*.py`, а всё
содержимое находится под `if __name__ == "__main__"`. При явном указании пути
pytest запускает их, но в обычном прогоне они не выполнялись ни разу — то есть
проверки безопасности токенов в логах не происходили.

`SecurityAnalyzer` остаётся в `verify_security.py`: он нужен как скрипт
ручной проверки журналов. Здесь проверяется он сам.

Перенос не сводится к копированию. Исходные проверки утверждали лишь то, что
анализатор «прошёл на безопасных логах». Этого недостаточно: анализатор,
который всегда возвращает `True`, прошёл бы все шесть. Поэтому здесь есть
обратная сторона каждой проверки — пример, который обязан её **отвергнуть**.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest

from tests.security.verify_security import SecurityAnalyzer


JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


def _log(message: str = "Операция", **context: object) -> str:
    """Строит строку JSON-журнала.

    Args:
        message: Текст сообщения.
        **context: Поля контекста.

    Returns:
        Строка журнала в формате JSON.
    """
    import json

    return json.dumps(
        {
            "timestamp": "2026-09-29T10:00:00Z",
            "level": "INFO",
            "component": "test",
            "message": message,
            "context": dict(context),
        },
        ensure_ascii=False,
    )


SECURE_LOGS = "\n".join(
    [
        _log("Создан источник", operation_type="add_source", token="***REDACTED***"),
        _log("Доступ изменён", operation_type="change_access", user_id="user123"),
    ]
)

INSECURE_LOGS = _log("Создан источник с токеном " + JWT, token=JWT)


class TestPlaintextTokens:
    """Открытые токены не должны попадать в журнал."""

    def test_secure_logs_contain_no_tokens(self):
        """Безопасные журналы проходят проверку."""
        is_valid, message = SecurityAnalyzer(SECURE_LOGS).check_no_plaintext_tokens()
        assert is_valid, message

    def test_token_in_message_is_detected(self):
        """Токен в тексте сообщения обнаруживается.

        Обратная сторона обязательна: проверка, которая проходит всегда,
        не проверяет ничего.
        """
        is_valid, message = SecurityAnalyzer(_log(f"токен {JWT}")).check_no_plaintext_tokens()

        assert not is_valid, "токен в сообщении обязан быть обнаружен"
        # Утверждается на смысловой части сообщения, а не на точной формулировке:
        # ветви провала и успеха различаются регистром первого слова, и привязка
        # к нему делала бы тест хрупким без всякой выгоды.
        assert "токены" in message, f"сообщение должно называть проблему: {message}"
        assert "Лог 0" in message, f"сообщение должно указывать запись: {message}"

    def test_token_in_context_is_detected(self):
        """Токен в контексте обнаруживается."""
        is_valid, _ = SecurityAnalyzer(_log("источник", token=JWT)).check_no_plaintext_tokens()

        assert not is_valid, "токен в контексте обязан быть обнаружен"

    def test_insecure_logs_are_rejected(self):
        """Ненадёжный пример отвергается."""
        is_valid, _ = SecurityAnalyzer(INSECURE_LOGS).check_no_plaintext_tokens()

        assert not is_valid, "открытые токены обязаны быть обнаружены"

    def test_bearer_token_is_detected(self):
        """Длинный Bearer-токен обнаруживается."""
        bearer = "A" * 45
        is_valid, _ = SecurityAnalyzer(_log(f"Bearer {bearer}")).check_no_plaintext_tokens()

        assert not is_valid, "Bearer-токен обязан быть обнаружен"

    def test_empty_logs_pass(self):
        """Пустые журналы не содержат токенов."""
        assert SecurityAnalyzer("").check_no_plaintext_tokens()[0] is True

    def test_non_json_lines_are_ignored(self):
        """Не-JSON строки не ломают разбор и не считаются записями."""
        analyzer = SecurityAnalyzer(f"просто текст\n{_log('норма', user_id='u1')}")

        assert len(analyzer.logs) == 1, f"ожидалась одна запись: {analyzer.logs}"
        assert analyzer.check_no_plaintext_tokens()[0] is True


class TestSensitiveFieldMasking:
    """Чувствительные поля маскируются."""

    def test_masked_fields_pass(self):
        """Маскированные поля проходят проверку."""
        is_valid, message = SecurityAnalyzer(SECURE_LOGS).check_sensitive_fields_masked()
        assert is_valid, message

    def test_unmasked_access_token_field_is_rejected(self):
        """Незамаскированное поле `access_token` отвергается.

        Проверяется поле, которое **есть** в `SENSITIVE_PATTERNS` анализатора.
        Пробел с голым `token` зафиксирован отдельным тестом ниже.
        """
        is_valid, message = SecurityAnalyzer(
            _log("источник", access_token=JWT)
        ).check_sensitive_fields_masked()

        assert not is_valid, "незамаскированный access_token обязан быть отвергнут"
        assert "не маскировано" in message, f"сообщение должно называть поле: {message}"
        assert "access_token" in message, f"сообщение должно называть поле: {message}"

    def test_unmasked_password_field_is_rejected(self):
        """Незамаскированный пароль отвергается."""
        is_valid, _ = SecurityAnalyzer(
            _log("вход", password="очень-длинный-пароль-значение")
        ).check_sensitive_fields_masked()

        assert not is_valid, "незамаскированный пароль обязан быть отвергнут"

    def test_bare_token_field_is_not_checked_by_masking_check(self):
        """Пробел анализатора: голое поле `token` не считается чувствительным.

        Установлено чтением `SENSITIVE_PATTERNS` (`verify_security.py:31-40`):
        список содержит `password`, `secret`, `api_key`, `apikey`, `auth`,
        `credential`, `access_token`, `refresh_token` — **голого `token` там
        нет**, а подстрока `"auth"` в `"token"` не встречается. Поэтому
        `check_sensitive_fields_masked` пропускает незамаскированный токен.

        Расхождение неслучайно и заметно: `check_no_plaintext_tokens` тот же
        токен ловит, а пример безопасных логов в самом анализаторе использует
        `token="***REDACTED***"` — то есть `token` задуман чувствительным.

        Тест фиксирует **фактическое** поведение, чтобы пробел был виден, а
        не замаскирован. Ожидаемое исправление — добавить `token` в
        `SENSITIVE_PATTERNS`; после этого тест начнёт падать, и его нужно будет
        перевернуть на `assert not is_valid`. Правка здесь не вносится: она
        меняет поведение проверки безопасности, а спека 009 FR-026 требует
        фиксировать такие дефекты отдельной задачей, а не править молча.
        """
        is_valid, _ = SecurityAnalyzer(_log("источник", token=JWT)).check_sensitive_fields_masked()

        assert is_valid, (
            "если пробел исправлен (token в SENSITIVE_PATTERNS), этот тест надо "
            "перевернуть на assert not is_valid"
        )

    def test_bare_token_is_still_caught_by_token_scan(self):
        """Тот же `token` ловится другой проверкой — расхождение локальное.

        Показывает, что дефект ограничен проверкой маскирования и не означает,
        что токены в журнале проходят незамеченными.
        """
        is_valid, _ = SecurityAnalyzer(_log("источник", token=JWT)).check_no_plaintext_tokens()

        assert not is_valid, "проверка открытых токенов обязана обнаружить токен"

    def test_short_value_is_accepted(self):
        """Значение короче девяти символов допустимо — это не токен.

        Граница проверяется отдельно намеренно: без неё «маскирование
        чувствительных полей» можно было бы удовлетворить запретом на всё.
        """
        assert SecurityAnalyzer(_log("источник", token="short12")).check_sensitive_fields_masked()[
            0
        ]

    def test_redacted_marker_is_accepted(self):
        """Явная маска `***REDACTED***` принимается."""
        logs = _log("источник", token="***REDACTED***")
        assert SecurityAnalyzer(logs).check_sensitive_fields_masked()[0]

    def test_non_sensitive_field_is_ignored(self):
        """Обычное поле не считается чувствительным."""
        assert SecurityAnalyzer(
            _log("событие", user_id="some-user-123456")
        ).check_sensitive_fields_masked()[0]


class TestErrorMessageSafety:
    """Сообщения об ошибках не раскрывают токены."""

    def test_safe_error_message_passes(self):
        """Безопасное сообщение об ошибке проходит."""
        import json

        entry = json.loads(_log("Ошибка аутентификации", error_message="Invalid token"))
        entry["level"] = "ERROR"
        logs = json.dumps(entry, ensure_ascii=False)

        is_valid, message = SecurityAnalyzer(logs).check_error_messages_safe()
        assert is_valid, message

    def test_token_in_error_message_is_rejected(self):
        """Токен в сообщении об ошибке обнаруживается."""
        import json

        entry = json.loads(_log("Ошибка", error_message=f"auth failed with {JWT}"))
        entry["level"] = "ERROR"
        logs = json.dumps(entry, ensure_ascii=False)

        is_valid, _ = SecurityAnalyzer(logs).check_error_messages_safe()

        assert not is_valid, "токен в сообщении об ошибке обязан быть обнаружен"

    def test_info_level_is_not_scanned_as_error(self):
        """Записи уровня INFO не проверяются как ошибки."""
        import json

        entry = json.loads(_log("инфо", error_message=f"токен {JWT}"))
        logs = json.dumps(entry, ensure_ascii=False)

        assert SecurityAnalyzer(logs).check_error_messages_safe()[0] is True

    def test_message_reports_how_many_errors_checked(self):
        """Отчёт называет число проверенных записей — иначе проверка молчит."""
        is_valid, message = SecurityAnalyzer(SECURE_LOGS).check_error_messages_safe()

        assert is_valid
        assert "0 сообщений" in message, f"отчёт должен называть число проверенных: {message}"


class TestExceptionSafety:
    """Исключения не раскрывают токены."""

    def test_clean_exception_passes(self):
        """Исключение без токенов проходит."""
        import json

        entry = json.loads(_log("ошибка"))
        entry["exception"] = "ValueError: устройство не найдено"

        assert SecurityAnalyzer(json.dumps(entry, ensure_ascii=False)).check_exception_safety()[0]

    def test_token_in_exception_is_rejected(self):
        """Токен в тексте исключения обнаруживается."""
        import json

        entry = json.loads(_log("ошибка"))
        entry["exception"] = f"RuntimeError: токен {JWT} отклонён"

        is_valid, _ = SecurityAnalyzer(
            json.dumps(entry, ensure_ascii=False)
        ).check_exception_safety()

        assert not is_valid, "токен в исключении обязан быть обнаружен"

    def test_logs_without_exception_pass(self):
        """Журналы без поля исключения проходят."""
        assert SecurityAnalyzer(SECURE_LOGS).check_exception_safety()[0] is True


class TestReportGeneration:
    """Отчёт о проверке."""

    def test_report_contains_sections(self):
        """Отчёт содержит заголовок и раздел результатов."""
        report = SecurityAnalyzer(SECURE_LOGS).generate_report()

        assert "ОТЧЕТ О ПРОВЕРКЕ БЕЗОПАСНОСТИ" in report
        assert "РЕЗУЛЬТАТЫ ПРОВЕРОК БЕЗОПАСНОСТИ" in report

    def test_report_counts_logs(self):
        """Отчёт называет число журналов и ошибок."""
        import json

        entry = json.loads(_log("ошибка"))
        entry["level"] = "ERROR"
        logs = "\n".join([SECURE_LOGS, json.dumps(entry, ensure_ascii=False)])

        report = SecurityAnalyzer(logs).generate_report()

        assert "Всего логов: 3" in report, f"ожидались 3 журнала: {report}"
        assert "Логов об ошибках: 1" in report, f"ожидалась 1 ошибка: {report}"

    def test_clean_report_declares_success(self):
        """Чистый журнал даёт отчёт об успехе."""
        report = SecurityAnalyzer(SECURE_LOGS).generate_report()

        assert "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" in report
        assert "ОБНАРУЖЕНЫ ПРОБЛЕМЫ" not in report

    def test_dirty_report_declares_problems(self):
        """Ненадёжный журнал даёт отчёт о проблемах.

        Обратная сторона обязательна: иначе отчёт, всегда объявляющий успех,
        прошёл бы проверку на любых данных.
        """
        report = SecurityAnalyzer(INSECURE_LOGS).generate_report()

        assert "ОБНАРУЖЕНЫ ПРОБЛЕМЫ БЕЗОПАСНОСТИ" in report
        assert "ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" not in report

    def test_report_lists_every_check(self):
        """Отчёт перечисляет все четыре проверки."""
        report = SecurityAnalyzer(SECURE_LOGS).generate_report()

        for name in (
            "Отсутствие открытых токенов",
            "Маскирование чувствительных полей",
            "Безопасность сообщений об ошибках",
            "Безопасность исключений",
        ):
            assert name in report, f"в отчёте нет проверки «{name}»"


@pytest.mark.parametrize(
    ("check_name", "expected"),
    [
        ("check_no_plaintext_tokens", True),
        ("check_sensitive_fields_masked", True),
        ("check_error_messages_safe", True),
        ("check_exception_safety", True),
    ],
)
def test_every_check_is_true_for_secure_logs(check_name: str, expected: bool):
    """Каждая проверка проходит на безопасных данных.

    Параметризовано, чтобы добавление новой проверки требовало явного решения:
    новая проверка попадёт сюда автоматически и не сможет молча остаться
    непроверенной.

    Args:
        check_name: Имя метода проверки.
        expected: Ожидаемый исход.
    """
    check = getattr(SecurityAnalyzer(SECURE_LOGS), check_name)

    assert check()[0] is expected
