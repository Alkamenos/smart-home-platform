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
    
    def clear(self) -> None:
        """Очистить реестр"""
        self._definitions.clear()
