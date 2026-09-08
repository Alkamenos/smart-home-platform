"""
FSM Graph Validator - Валидация определений конечных автоматов

Проверяет корректность графа FSM перед регистрацией:
1. initial состояние есть в списке states
2. Все to_state в переходах существуют в states
3. Все from_state (если не "*") существуют в states
4. Есть хотя бы один исходящий переход из initial состояния
5. Граф связный (все состояния достижимы из initial)
6. Нет дубликатов (from_state, trigger) с одинаковым приоритетом
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple, Any
from collections import defaultdict


# Определяем классы локально чтобы избежать циклического импорта
@dataclass(frozen=True)
class Transition:
    """Описание перехода между состояниями"""
    
    from_state: str | tuple[str, ...]  # Из какого состояния ("*" = из любого)
    to_state: str                      # В какое состояние
    trigger: str                       # Событие, вызывающее переход
    guard: Callable[[dict], bool] = lambda ctx: True  # Условие
    priority: int = 0                  # Приоритет (выше = важнее)
    reason: str = ""                   # Описание
    timeout_sec: Optional[int] = None  # Таймаут для перехода в следующее состояние
    attributes: dict = field(default_factory=dict)  # Атрибуты для команды
    debounce_sec: float = 0.0          # Защита от дребезга
    action: Optional[Callable[[dict], None]] = None  # Действие при выполнении
    cooldown_sec: float = 0.0          # Мин. время после предыдущего перехода
    manual_lockout_min: float = 0.0    # Блокировка автоматики после ручного


@dataclass(frozen=True)
class FSMDefinition:
    """Описание автомата"""
    
    entity_id: str                     # ID устройства
    states: tuple[str, ...]            # Все возможные состояния
    initial: str                       # Начальное состояние
    transitions: tuple[Transition, ...]  # Все переходы


class FSMValidationError(Exception):
    """Исключение при ошибке валидации FSM"""
    
    def __init__(self, message: str, entity_id: str = None):
        self.entity_id = entity_id
        full_message = f"[{entity_id}] {message}" if entity_id else message
        super().__init__(full_message)


def validate_definition(definition: FSMDefinition) -> None:
    """
    Валидировать определение FSM
    
    Args:
        definition: Определение автомата для проверки
        
    Raises:
        FSMValidationError: При обнаружении ошибок в графе
    """
    entity_id = definition.entity_id
    states = set(definition.states)
    initial = definition.initial
    transitions = definition.transitions
    
    # Проверка 1: initial состояние есть в списке states
    if initial not in states:
        raise FSMValidationError(
            f"Initial state '{initial}' not found in states {list(states)}",
            entity_id
        )
    
    # Проверка 2 и 3: Все from_state и to_state существуют в states
    for i, transition in enumerate(transitions):
        # Проверяем to_state
        if transition.to_state not in states:
            raise FSMValidationError(
                f"Transition #{i}: to_state '{transition.to_state}' not found in states {list(states)}",
                entity_id
            )
        
        # Проверяем from_state (если не "*")
        if transition.from_state != "*":
            if isinstance(transition.from_state, tuple):
                for state in transition.from_state:
                    if state not in states:
                        raise FSMValidationError(
                            f"Transition #{i}: from_state '{state}' not found in states {list(states)}",
                            entity_id
                        )
            else:
                if transition.from_state not in states:
                    raise FSMValidationError(
                        f"Transition #{i}: from_state '{transition.from_state}' not found in states {list(states)}",
                        entity_id
                    )
    
    # Проверка 4: Есть хотя бы один исходящий переход из initial состояния
    has_outgoing_from_initial = False
    for transition in transitions:
        if transition.from_state == "*" or transition.from_state == initial:
            has_outgoing_from_initial = True
            break
        
        if isinstance(transition.from_state, tuple) and initial in transition.from_state:
            has_outgoing_from_initial = True
            break
    
    if not has_outgoing_from_initial:
        raise FSMValidationError(
            f"No outgoing transitions from initial state '{initial}'",
            entity_id
        )
    
    # Проверка 5: Граф связный (все состояния достижимы из initial)
    _validate_graph_connectivity(definition)
    
    # Проверка 6: Нет дубликатов (from_state, trigger) с одинаковым приоритетом
    _validate_duplicate_transitions(definition)


def _validate_graph_connectivity(definition: FSMDefinition) -> None:
    """
    Проверить что все состояния достижимы из initial
    
    Использует алгоритм обхода графа в ширину (BFS).
    
    Args:
        definition: Определение автомата для проверки
        
    Raises:
        FSMValidationError: Если есть недостижимые состояния
    """
    states = set(definition.states)
    initial = definition.initial
    transitions = definition.transitions
    
    # Строим adjacency list для графа состояний
    adjacency: dict[str, list[str]] = defaultdict(list)
    
    for transition in transitions:
        from_states = []
        
        if transition.from_state == "*":
            from_states = list(states)
        elif isinstance(transition.from_state, tuple):
            from_states = list(transition.from_state)
        else:
            from_states = [transition.from_state]
        
        for from_state in from_states:
            adjacency[from_state].append(transition.to_state)
    
    # BFS обход из initial состояния
    visited: set[str] = set()
    queue: list[str] = [initial]
    visited.add(initial)
    
    while queue:
        current = queue.pop(0)
        for neighbor in adjacency[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    
    # Проверяем что все состояния посещены
    unreachable = states - visited
    
    if unreachable:
        raise FSMValidationError(
            f"Unreachable states from initial '{initial}': {list(unreachable)}",
            entity_id=definition.entity_id
        )


def _validate_duplicate_transitions(definition: FSMDefinition) -> None:
    """
    Проверить что нет дубликатов (from_state, trigger) с одинаковым приоритетом
    
    Дубликаты с разными приоритетами допустимы (более высокий приоритет победит).
    Но дубликаты с одинаковым приоритетом создают неопределённость.
    
    Args:
        definition: Определение автомата для проверки
        
    Raises:
        FSMValidationError: Если найдены дубликаты с одинаковым приоритетом
    """
    transitions = definition.transitions
    
    # Группируем переходы по ключу (normalized_from_state, trigger, priority)
    transition_map: dict[tuple, list[Transition]] = defaultdict(list)
    
    for transition in transitions:
        # Нормализуем from_state для ключа
        if transition.from_state == "*":
            # Для "*" создаём отдельный ключ
            from_key = "*"
        elif isinstance(transition.from_state, tuple):
            # Сортируем кортеж чтобы ("A", "B") и ("B", "A") были одинаковыми
            from_key = tuple(sorted(transition.from_state))
        else:
            from_key = transition.from_state
        
        key = (from_key, transition.trigger, transition.priority)
        transition_map[key].append(transition)
    
    # Ищем дубликаты
    for key, duplicates in transition_map.items():
        if len(duplicates) > 1:
            from_state, trigger, priority = key
            raise FSMValidationError(
                f"Duplicate transitions with same (from_state={from_state}, trigger='{trigger}', priority={priority}): "
                f"{len(duplicates)} transitions found to states {[t.to_state for t in duplicates]}",
                entity_id=definition.entity_id
            )
