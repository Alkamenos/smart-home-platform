"""
Registry - Реестр для регистрации guard и action функций.

Этот модуль позволяет безопасно регистрировать и вызывать функции по имени,
без использования eval(). Используется для YAML-конфигураций автоматов.
"""

from __future__ import annotations

from typing import Any, Callable


class Registry:
    """
    Реестр для регистрации guard и action функций.
    
    Позволяет безопасно вызывать функции по имени из YAML-конфигураций.
    
    Usage:
        registry = Registry()
        registry.register_guard("is_night_time", is_night_time_fn)
        registry.register_action("turn_on_light", turn_on_light_fn)
        
        # Проверка наличия
        if registry.has_guard("is_night_time"):
            result = registry.get_guard("is_night_time")(context)
    """

    def __init__(self) -> None:
        self._guards: dict[str, Callable[..., bool]] = {}
        self._actions: dict[str, Callable[..., Any]] = {}

    def register_guard(self, name: str, guard_fn: Callable[..., bool]) -> None:
        """
        Зарегистрировать функцию guard по имени.
        
        Args:
            name: Имя для регистрации (используется в YAML).
            guard_fn: Функция, принимающая контекст и возвращающая bool.
        """
        self._guards[name] = guard_fn

    def register_action(self, name: str, action_fn: Callable[..., Any]) -> None:
        """
        Зарегистрировать функцию action по имени.
        
        Args:
            name: Имя для регистрации (используется в YAML).
            action_fn: Функция, принимающая контекст (может быть async).
        """
        self._actions[name] = action_fn

    def has_guard(self, name: str) -> bool:
        """Проверить, зарегистрирован ли guard с данным именем."""
        return name in self._guards

    def has_action(self, name: str) -> bool:
        """Проверить, зарегистрирован ли action с данным именем."""
        return name in self._actions

    def get_guard(self, name: str) -> Callable[..., bool] | None:
        """Получить функцию guard по имени."""
        return self._guards.get(name)

    def get_action(self, name: str) -> Callable[..., Any] | None:
        """Получить функцию action по имени."""
        return self._actions.get(name)

    def list_guards(self) -> list[str]:
        """Вернуть список всех зарегистрированных guard'ов."""
        return list(self._guards.keys())

    def list_actions(self) -> list[str]:
        """Вернуть список всех зарегистрированных actions."""
        return list(self._actions.keys())

    def clear(self) -> None:
        """Очистить весь реестр."""
        self._guards.clear()
        self._actions.clear()
