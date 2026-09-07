"""
Logger - Структурированное логирование с контекстом

Формат логов:
{"timestamp", "level", "component", "entity_id", "message", "context"}
"""

from __future__ import annotations
import json
import time
import logging
from datetime import datetime, timezone


# Глобальный кэш логгеров
_loggers_cache = {}


def get_logger(component: str = "platform") -> logging.Logger:
    """
    Получить инстанс логгера для компонента
    
    Args:
        component: Название компонента
        
    Returns:
        logging.Logger: Настроенный логгер
    """
    if component in _loggers_cache:
        return _loggers_cache[component]
    
    # Создаем логгер
    logger = logging.getLogger(f"platform_v3.{component}")
    logger.setLevel(logging.DEBUG)
    
    # Если еще нет handlers, добавляем
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        
        # Формат с компонентом
        formatter = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    _loggers_cache[component] = logger
    return logger


class Logger:
    """
    Структурированный логгер (для тестов)

    Usage:
        logger = Logger(component="fsm")
        logger.info("Transition occurred", entity_id="light.living_room")
        logger.error("Failed to process event", error="...")
    """

    def __init__(self, component: str = "platform", output: str = "stdout"):
        self._component = component
        self._output = output  # "stdout", "file", или callback
        self._logs: list[dict] = []  # Для тестирования

    def _format_log(self, level: str, message: str, **context) -> dict:
        """Сформировать структурированный лог"""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "component": self._component,
            "message": message,
            "context": context,
        }

    def _write(self, log_entry: dict) -> None:
        """Записать лог"""
        self._logs.append(log_entry)

        if self._output == "stdout":
            print(json.dumps(log_entry, ensure_ascii=False))

    def info(self, message: str, **context) -> None:
        """Информационное сообщение"""
        self._write(self._format_log("INFO", message, **context))

    def debug(self, message: str, **context) -> None:
        """Отладочное сообщение"""
        self._write(self._format_log("DEBUG", message, **context))

    def warning(self, message: str, **context) -> None:
        """Предупреждение"""
        self._write(self._format_log("WARNING", message, **context))

    def error(self, message: str, **context) -> None:
        """Ошибка"""
        self._write(self._format_log("ERROR", message, **context))

    def get_logs(self, level: str = None) -> list[dict]:
        """Получить все логи (для тестов)"""
        if level is None:
            return list(self._logs)
        return [log for log in self._logs if log["level"] == level]

    def clear(self) -> None:
        """Очистить логи"""
        self._logs.clear()
