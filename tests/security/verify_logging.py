"""
Скрипт проверки полноты логирования операций в Smart Home Platform.

Проверяет что все критические операции логируются с полной информацией:
- Добавление источника HA
- Синхронизация устройств
- Обновление конфигурации
- Отправка команд
- Изменение доступа

Каждый лог должен содержать:
- timestamp (ISO 8601)
- operation_type
- user_id (для user-initiated операций)
- source_id и device_id (где применимо)
- result (success/error)
- operation details
"""

import json
import re
from typing import Any

import pytest


class LogAnalyzer:
    """Анализатор логов для проверки полноты логирования."""

    # Требуемые поля в логе
    REQUIRED_FIELDS = {
        "timestamp",
        "level",
        "component",
        "message",
    }

    # Необходимые поля для операционных логов
    OPERATION_FIELDS = {
        "operation_type",
        "result",
    }

    # Типы операций которые должны логироваться
    EXPECTED_OPERATIONS = {
        "add_source",
        "sync_devices",
        "update_config",
        "send_command",
        "change_access",
        "remove_source",
    }

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

    def check_required_fields(self) -> tuple[bool, str]:
        """Проверяет что все логи содержат обязательные поля.

        Returns:
            (is_valid, message)
        """
        for i, log in enumerate(self.logs):
            missing = self.REQUIRED_FIELDS - set(log.keys())
            if missing:
                return False, f"Лог {i} отсутствуют поля: {missing}"
        return True, "Все логи содержат обязательные поля"

    def check_timestamp_format(self) -> tuple[bool, str]:
        """Проверяет что timestamp в формате ISO 8601.

        Returns:
            (is_valid, message)
        """
        iso_pattern = re.compile(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?"
        )
        invalid_count = 0
        for log in self.logs:
            timestamp = log.get("timestamp", "")
            if not iso_pattern.match(str(timestamp)):
                invalid_count += 1

        if invalid_count > 0:
            return False, f"{invalid_count} логов имеют неправильный формат timestamp"
        return True, "Все timestamp в формате ISO 8601"

    def check_operation_completeness(self) -> tuple[bool, str]:
        """Проверяет что операционные логи содержат все необходимые поля.

        Returns:
            (is_valid, message)
        """
        operation_logs = [log for log in self.logs if log.get("context", {}).get("operation_type")]

        if not operation_logs:
            return False, "Не найдены логи операций с operation_type"

        missing_ops = self.EXPECTED_OPERATIONS.copy()
        found_ops = set()

        for log in operation_logs:
            context = log.get("context", {})
            op_type = context.get("operation_type")
            if op_type:
                found_ops.add(op_type)
                missing_ops.discard(op_type)

            # Проверяем наличие result
            if "result" not in context:
                return False, f"Лог операции {op_type} отсутствует поле result"

            # Проверяем result значение (success/error)
            if context.get("result") not in ("success", "error"):
                return False, (
                    f"Лог операции {op_type} имеет неправильное значение result: "
                    f"{context.get('result')}"
                )

        if missing_ops:
            return False, f"Отсутствуют логи для операций: {missing_ops}"

        return True, f"Найдены логи всех операций: {found_ops}"

    def check_context_fields(self) -> tuple[bool, str]:
        """Проверяет что операционные логи содержат правильный контекст.

        Returns:
            (is_valid, message)
        """
        operation_logs = [log for log in self.logs if log.get("context", {}).get("operation_type")]

        for log in operation_logs:
            context = log.get("context", {})
            op_type = context.get("operation_type")

            # user-initiated операции должны содержать user_id
            if (
                op_type in ("add_source", "update_config", "send_command", "change_access")
                and "user_id" not in context
                and context.get("result") != "error"
            ):
                return False, f"Лог {op_type} отсутствует user_id"

            # Операции с устройствами должны содержать device_id
            if (
                op_type in ("send_command", "change_access", "sync_devices")
                and "device_id" not in context
                and context.get("result") != "error"
            ):
                return False, f"Лог {op_type} отсутствует device_id"

            # Операции с источниками должны содержать source_id
            if (
                op_type in ("add_source", "remove_source", "sync_devices")
                and "source_id" not in context
                and context.get("result") != "error"
            ):
                return False, f"Лог {op_type} отсутствует source_id"

        return True, "Контекст логов содержит все необходимые поля"

    def check_error_logging(self) -> tuple[bool, str]:
        """Проверяет что ошибки логируются правильно.

        Returns:
            (is_valid, message)
        """
        error_logs = [log for log in self.logs if log.get("level") == "ERROR"]

        if not error_logs:
            # Может быть нормально если нет ошибок
            return True, "Нет логов об ошибках"

        for log in error_logs:
            context = log.get("context", {})

            # Ошибка должна иметь result=error
            if context.get("result") != "error":
                return False, "Лог об ошибке должен иметь result=error"

            # Ошибка должна содержать детали
            if "error_message" not in context:
                return False, "Лог об ошибке должен содержать error_message"

        return True, f"Найдено {len(error_logs)} логов об ошибках с корректной структурой"

    def generate_report(self) -> str:
        """Генерирует отчет о проверке логирования.

        Returns:
            Форматированный отчет
        """
        report_lines = [
            "=" * 80,
            "ОТЧЕТ О ПРОВЕРКЕ ЛОГИРОВАНИЯ",
            "=" * 80,
            "",
        ]

        # Статистика
        report_lines.extend(
            [
                f"Всего логов в файле: {len(self.logs)}",
                f"Логов об операциях: {len([log_entry for log_entry in self.logs if log_entry.get('context', {}).get('operation_type')])}",
                f"Логов об ошибках: {len([log_entry for log_entry in self.logs if log_entry.get('level') == 'ERROR'])}",
                "",
            ]
        )

        # Результаты проверок
        checks = [
            ("Обязательные поля", self.check_required_fields()),
            ("Формат timestamp", self.check_timestamp_format()),
            ("Полнота операций", self.check_operation_completeness()),
            ("Поля контекста", self.check_context_fields()),
            ("Логирование ошибок", self.check_error_logging()),
        ]

        report_lines.append("РЕЗУЛЬТАТЫ ПРОВЕРОК:")
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
                f"ИТОГО: {'ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ' if all_passed else 'НЕКОТОРЫЕ ПРОВЕРКИ НЕ ПРОЙДЕНЫ'}",
                "=" * 80,
            ]
        )

        return "\n".join(report_lines)


# Tests


@pytest.fixture
def sample_logs():
    """Пример логов для тестирования."""
    return """{"timestamp": "2026-09-29T10:00:00Z", "level": "INFO", "component": "sources", "message": "Создан источник", "context": {"operation_type": "add_source", "source_id": "550e8400-e29b-41d4-a716-446655440000", "user_id": "admin_user", "result": "success"}}
{"timestamp": "2026-09-29T10:00:01Z", "level": "INFO", "component": "devices", "message": "Синхронизация устройств начата", "context": {"operation_type": "sync_devices", "source_id": "550e8400-e29b-41d4-a716-446655440000", "result": "success", "devices_count": 5}}
{"timestamp": "2026-09-29T10:00:02Z", "level": "INFO", "component": "config", "message": "Конфигурация обновлена", "context": {"operation_type": "update_config", "user_id": "admin_user", "result": "success", "config_section": "automation"}}
{"timestamp": "2026-09-29T10:00:03Z", "level": "INFO", "component": "commands", "message": "Команда отправлена", "context": {"operation_type": "send_command", "user_id": "user_123", "device_id": "light.kitchen", "result": "success", "service": "turn_on"}}
{"timestamp": "2026-09-29T10:00:04Z", "level": "INFO", "component": "access", "message": "Доступ изменен", "context": {"operation_type": "change_access", "user_id": "admin_user", "device_id": "light.bedroom", "result": "success", "target_user": "user_456", "role": "controller"}}
{"timestamp": "2026-09-29T10:00:05Z", "level": "ERROR", "component": "sources", "message": "Ошибка удаления источника", "context": {"operation_type": "remove_source", "source_id": "550e8400-e29b-41d4-a716-446655440000", "result": "error", "error_message": "Источник используется устройствами"}}"""


def test_required_fields(sample_logs):
    """Проверяет наличие обязательных полей."""
    analyzer = LogAnalyzer(sample_logs)
    is_valid, message = analyzer.check_required_fields()
    assert is_valid, message


def test_timestamp_format(sample_logs):
    """Проверяет формат timestamp."""
    analyzer = LogAnalyzer(sample_logs)
    is_valid, message = analyzer.check_timestamp_format()
    assert is_valid, message


def test_operation_completeness(sample_logs):
    """Проверяет полноту операционных логов."""
    analyzer = LogAnalyzer(sample_logs)
    is_valid, message = analyzer.check_operation_completeness()
    assert is_valid, message


def test_context_fields(sample_logs):
    """Проверяет наличие необходимых полей контекста."""
    analyzer = LogAnalyzer(sample_logs)
    is_valid, message = analyzer.check_context_fields()
    assert is_valid, message


def test_error_logging(sample_logs):
    """Проверяет логирование ошибок."""
    analyzer = LogAnalyzer(sample_logs)
    is_valid, message = analyzer.check_error_logging()
    assert is_valid, message


def test_report_generation(sample_logs):
    """Проверяет генерацию отчета."""
    analyzer = LogAnalyzer(sample_logs)
    report = analyzer.generate_report()
    assert "ОТЧЕТ О ПРОВЕРКЕ ЛОГИРОВАНИЯ" in report
    assert "РЕЗУЛЬТАТЫ ПРОВЕРОК" in report


if __name__ == "__main__":
    # Запуск тестов и генерация отчета
    pytest.main([__file__, "-v", "--tb=short"])
