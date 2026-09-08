"""
Registry - Реестр всех зарегистрированных автоматов
"""

from __future__ import annotations
from .fsm import FSMDefinition, State


class Registry:
    """
    Реестр автоматов
    
    Usage:
        registry = Registry()
        registry.register_all(definitions)
        entity_ids = registry.get_all_entity_ids()
    """
    
    def __init__(self):
        self._definitions: dict[str, FSMDefinition] = {}
    
    def register(self, definition: FSMDefinition) -> None:
        """Зарегистрировать один автомат"""
        self._definitions[definition.entity_id] = definition
    
    def register_all(self, definitions: list[FSMDefinition]) -> None:
        """Зарегистрировать список автоматов"""
        for definition in definitions:
            self.register(definition)
    
    def get(self, entity_id: str) -> FSMDefinition | None:
        """Получить определение автомата"""
        return self._definitions.get(entity_id)
    
    def get_all_entity_ids(self) -> list[str]:
        """Получить все entity_id"""
        return list(self._definitions.keys())
    
    def get_states_snapshot(self, fsm_engine) -> dict[str, State]:
        """Получить снимок всех состояний"""
        return fsm_engine.get_all_states()
    
    def count(self) -> int:
        """Получить количество зарегистрированных автоматов"""
        return len(self._definitions)
    
    def get_all_required_entities(self) -> set[str]:
        """
        Собирает множество всех entity_id, которые используются в зарегистрированных FSM.
        Необходимо для создания точечных подписок вместо глобальной '@state_changed("*")'.
        
        Returns:
            set[str]: Множество уникальных entity_id и wildcard-паттернов.
        """
        entities = set()
        for definition in self._definitions.values():
            # Проверяем триггеры (обычно это entity_id или домены)
            for transition in definition.transitions:
                trigger = transition.trigger
                # Если триггер похож на entity_id (содержит точку) или wildcard
                if '.' in trigger:
                    entities.add(trigger)
            
            # Проверяем действия (actions), так как они тоже могут зависеть от entity_id
            for transition in definition.transitions:
                action = transition.action
                if action and '.' in action:
                    # Пытаемся извлечь entity_id из строки действия, если она там есть
                    # Формат может быть: "light.turn_on(entity_id='light.kitchen')"
                    import re
                    match = re.search(r"entity_id=['\"]([^'\"]+)['\"]", action)
                    if match:
                        entities.add(match.group(1))
        
        return entities
    
    def clear(self) -> None:
        """Очистить реестр"""
        self._definitions.clear()
