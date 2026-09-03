"""
Валидатор графа переходов FSM.
Проверяет:
1. Все to-состояния существуют в states
2. Все from-состояния существуют в states
3. Нет недостижимых состояний (BFS от initial)
4. Нет deadlock (состояния без исходящих переходов, кроме terminal)
5. Нет зацикливаний с одинаковым приоритетом
6. PREVIOUS используется корректно
"""

from typing import Dict, Any, List, Set, Tuple, Optional
from collections import deque


# Специальные константы
PREVIOUS = "PREVIOUS"
WILDCARD = "*"


class FSMValidationError(Exception):
    """Исключение для ошибок валидации FSM."""
    pass


class FSMValidationResult:
    """Результат валидации FSM."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
    
    def add_error(self, message: str):
        self.errors.append(message)
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def add_info(self, message: str):
        self.info.append(message)
    
    def is_valid(self) -> bool:
        return len(self.errors) == 0
    
    def __str__(self) -> str:
        lines = []
        if self.is_valid():
            lines.append("✅ Валидация пройдена успешно")
        else:
            lines.append(f"❌ Найдено ошибок: {len(self.errors)}")
        
        if self.errors:
            lines.append("\nОшибки:")
            for err in self.errors:
                lines.append(f"  - {err}")
        
        if self.warnings:
            lines.append(f"\nПредупреждения ({len(self.warnings)}):")
            for warn in self.warnings:
                lines.append(f"  - {warn}")
        
        if self.info:
            lines.append(f"\nИнформация ({len(self.info)}):")
            for inf in self.info:
                lines.append(f"  - {inf}")
        
        return "\n".join(lines)


def validate_states_exist(definition: Dict[str, Any], result: FSMValidationResult):
    """Проверка 1 & 2: Все from/to состояния существуют в списке states."""
    states_raw = definition.get("states", [])
    
    # Обработка states как списка или словаря
    if isinstance(states_raw, list):
        states = set(states_raw)
    elif isinstance(states_raw, dict):
        states = set(states_raw.keys())
    else:
        result.add_error("Поле 'states' должно быть списком или словарем")
        return
    
    transitions = definition.get("transitions", [])
    
    for i, transition in enumerate(transitions):
        from_state = transition.get("from")
        to_state = transition.get("to")
        
        # Проверка from (может быть строкой, списком или "*" wildcard)
        if isinstance(from_state, list):
            for fs in from_state:
                if fs != WILDCARD and fs not in states:
                    result.add_error(
                        f"Переход #{i}: состояние '{fs}' не найдено в списке states"
                    )
        elif from_state and from_state != WILDCARD and from_state not in states:
            result.add_error(
                f"Переход #{i}: состояние '{from_state}' не найдено в списке states"
            )
        
        # Проверка to
        if to_state and to_state != PREVIOUS and to_state not in states:
            result.add_error(
                f"Переход #{i}: целевое состояние '{to_state}' не найдено в списке states"
            )


def validate_reachable_states(definition: Dict[str, Any], result: FSMValidationResult):
    """Проверка 3: Нет недостижимых состояний (BFS от initial)."""
    states_raw = definition.get("states", [])
    
    # Обработка states как списка или словаря
    if isinstance(states_raw, list):
        states = set(states_raw)
    elif isinstance(states_raw, dict):
        states = set(states_raw.keys())
    else:
        return  # Уже обработано в validate_states_exist
    
    initial_state = definition.get("initial_state") or definition.get("initial")
    transitions = definition.get("transitions", [])
    
    if not initial_state:
        result.add_error("Не указано начальное состояние (initial_state или initial)")
        return
    
    if initial_state not in states:
        result.add_error(f"Начальное состояние '{initial_state}' не найдено в списке states")
        return
    
    # Построение графа переходов
    graph: Dict[str, Set[str]] = {state: set() for state in states}
    
    for transition in transitions:
        from_state = transition.get("from")
        to_state = transition.get("to")
        
        # Обработка from_state (строка, список, wildcard)
        from_states_list = []
        if isinstance(from_state, list):
            from_states_list = from_state
        elif from_state == WILDCARD:
            from_states_list = list(states)
        elif from_state:
            from_states_list = [from_state]
        
        for fs in from_states_list:
            if fs == WILDCARD:
                for state in states:
                    if to_state == PREVIOUS:
                        continue
                    if to_state and to_state in states:
                        graph[state].add(to_state)
            elif fs in states:
                if to_state == PREVIOUS:
                    continue
                if to_state and to_state in states:
                    graph[fs].add(to_state)
    
    # BFS от начального состояния
    reachable = set()
    queue = deque([initial_state])
    reachable.add(initial_state)
    
    while queue:
        current = queue.popleft()
        for neighbor in graph.get(current, []):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)
    
    # Поиск недостижимых состояний
    unreachable = states - reachable
    if unreachable:
        result.add_error(f"Недостижимые состояния: {', '.join(sorted(unreachable))}")
    else:
        result.add_info("Все состояния достижимы из начального")


def validate_no_deadlock(definition: Dict[str, Any], result: FSMValidationResult):
    """Проверка 4: Нет deadlock (состояния без исходящих переходов)."""
    states_raw = definition.get("states", [])
    
    # Обработка states как списка или словаря
    if isinstance(states_raw, list):
        states = set(states_raw)
    elif isinstance(states_raw, dict):
        states = set(states_raw.keys())
    else:
        return  # Уже обработано
    
    initial_state = definition.get("initial_state") or definition.get("initial")
    transitions = definition.get("transitions", [])
    
    # Определение terminal состояний (допустимо отсутствие исходящих переходов)
    # Обычно это состояния типа ERROR, LOCKOUT, TERMINAL, FAULT
    terminal_keywords = ["ERROR", "LOCKOUT", "TERMINAL", "FAULT"]
    terminal_states = {
        s for s in states 
        if any(keyword in s.upper() for keyword in terminal_keywords)
    }
    
    # Построение множества состояний с исходящими переходами
    has_outgoing = set()
    
    for transition in transitions:
        from_state = transition.get("from")
        
        # Обработка from_state (строка, список, wildcard)
        if isinstance(from_state, list):
            has_outgoing.update(from_state)
        elif from_state == WILDCARD:
            has_outgoing.update(states)
        elif from_state:
            has_outgoing.add(from_state)
    
    # Проверка состояний без исходящих переходов
    no_outgoing = states - has_outgoing
    
    # Исключаем начальное состояние (оно может быть временным)
    no_outgoing.discard(initial_state)
    
    # Проверяем только нетерминальные состояния
    problematic = no_outgoing - terminal_states
    if problematic:
        result.add_error(
            f"Deadlock состояния (нет исходящих переходов): {', '.join(sorted(problematic))}"
        )
    elif no_outgoing and no_outgoing != terminal_states:
        # Terminal состояния без исходящих - это нормально
        pass
    else:
        result.add_info("Нет deadlock состояний")


def validate_priority_cycles(definition: Dict[str, Any], result: FSMValidationResult):
    """Проверка 5: Нет зацикливаний с одинаковым приоритетом."""
    transitions = definition.get("transitions", [])
    
    # Группировка переходов по приоритету
    priority_groups: Dict[int, List[Dict]] = {}
    for transition in transitions:
        priority = transition.get("priority", 0)
        if priority not in priority_groups:
            priority_groups[priority] = []
        priority_groups[priority].append(transition)
    
    # Для каждого приоритета проверяем циклы
    for priority, group in priority_groups.items():
        # Строим граф для этого приоритета
        graph: Dict[str, Set[str]] = {}
        
        for transition in group:
            from_state = transition.get("from")
            to_state = transition.get("to")
            
            # Пропускаем wildcard и PREVIOUS
            if from_state == WILDCARD or to_state == PREVIOUS:
                continue
            
            # Обработка from_state как списка
            from_states_list = []
            if isinstance(from_state, list):
                from_states_list = from_state
            elif from_state:
                from_states_list = [from_state]
            
            for fs in from_states_list:
                if fs == WILDCARD:
                    continue
                if fs not in graph:
                    graph[fs] = set()
                if to_state:
                    graph[fs].add(to_state)
        
        # Поиск циклов DFS
        visited = set()
        rec_stack = set()
        cycles_found = []
        
        def dfs_cycle(node: str, path: List[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if dfs_cycle(neighbor, path + [neighbor]):
                        return True
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor) if neighbor in path else 0
                    cycle = path[cycle_start:] + [neighbor]
                    cycles_found.append(cycle)
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in graph:
            if node not in visited:
                dfs_cycle(node, [node])
        
        if cycles_found:
            for cycle in cycles_found[:3]:  # Показываем первые 3 цикла
                result.add_warning(
                    f"Возможный цикл с приоритетом {priority}: {' -> '.join(cycle)}"
                )
    
    if not any("цикл" in str(w).lower() for w in result.warnings):
        result.add_info("Подозрительных циклов с одинаковым приоритетом не найдено")


def validate_previous_usage(definition: Dict[str, Any], result: FSMValidationResult):
    """Проверка 6: PREVIOUS используется корректно."""
    transitions = definition.get("transitions", [])
    states = set(definition.get("states", []))
    
    previous_transitions = [t for t in transitions if t.get("to") == PREVIOUS]
    
    for transition in previous_transitions:
        from_state = transition.get("from")
        priority = transition.get("priority", 0)
        
        # PREVIOUS должен иметь fallback состояние или использоваться с низким приоритетом
        # Проверяем есть ли другие переходы из того же состояния
        same_from = [t for t in transitions if t.get("from") == from_state]
        
        if len(same_from) == 1:
            result.add_warning(
                f"Переход с PREVIOUS из '{from_state}' - единственный переход, "
                f"PREVIOUS может быть не определен при старте"
            )
    
    if previous_transitions:
        result.add_info(f"Найдено переходов с PREVIOUS: {len(previous_transitions)}")


def validate_fsm(definition: Dict[str, Any]) -> FSMValidationResult:
    """
    Основная функция валидации FSM.
    
    Args:
        definition: Словарь с определением FSM
    
    Returns:
        FSMValidationResult с ошибками, предупреждениями и информацией
    """
    result = FSMValidationResult()
    
    # Базовая проверка структуры
    if not isinstance(definition, dict):
        result.add_error("Определение FSM должно быть словарем")
        return result
    
    if "states" not in definition:
        result.add_error("Отсутствует поле 'states'")
        return result
    
    if "transitions" not in definition:
        result.add_error("Отсутствует поле 'transitions'")
        return result
    
    if not definition.get("states"):
        result.add_error("Список состояний пуст")
        return result
    
    if not definition.get("transitions"):
        result.add_error("Список переходов пуст")
        return result
    
    # Запуск всех проверок
    validate_states_exist(definition, result)
    validate_reachable_states(definition, result)
    validate_no_deadlock(definition, result)
    validate_priority_cycles(definition, result)
    validate_previous_usage(definition, result)
    
    return result


def validate_multiple_fsm(fsm_definitions: Dict[str, Dict[str, Any]]) -> Dict[str, FSMValidationResult]:
    """
    Валидировать несколько FSM определений.
    
    Args:
        fsm_definitions: Словарь {name: definition}
    
    Returns:
        Словарь {name: FSMValidationResult}
    """
    results = {}
    for name, definition in fsm_definitions.items():
        results[name] = validate_fsm(definition)
    return results


def print_validation_report(results: Dict[str, FSMValidationResult]):
    """Вывести отчет валидации в консоль."""
    print("=" * 60)
    print("ОТЧЕТ ВАЛИДАЦИИ FSM")
    print("=" * 60)
    
    all_valid = True
    
    for name, result in results.items():
        print(f"\n📋 FSM: {name}")
        print("-" * 40)
        
        if result.is_valid():
            print(f"✅ Статус: VALID")
        else:
            print(f"❌ Статус: INVALID")
            all_valid = False
        
        # Краткий вывод
        if result.errors:
            print(f"   Ошибки: {len(result.errors)}")
        if result.warnings:
            print(f"   Предупреждения: {len(result.warnings)}")
        if result.info:
            print(f"   Информация: {len(result.info)}")
    
    print("\n" + "=" * 60)
    if all_valid:
        print("✅ ВСЕ FSM ПРОШЛИ ВАЛИДАЦИЮ")
    else:
        print("❌ ОБНАРУЖЕНЫ ОШИБКИ В FSM")
    print("=" * 60)
    
    return all_valid


# CLI интерфейс
if __name__ == "__main__":
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Использование: python fsm_validate.py <fsm_file.json>")
        print("Или передайте JSON через stdin")
        sys.exit(1)
    
    try:
        # Чтение из файла
        if sys.argv[1] == "-":
            fsm_def = json.load(sys.stdin)
        else:
            with open(sys.argv[1], 'r', encoding='utf-8') as f:
                fsm_def = json.load(f)
        
        result = validate_fsm(fsm_def)
        print(result)
        
        sys.exit(0 if result.is_valid() else 1)
    
    except FileNotFoundError:
        print(f"❌ Файл не найден: {sys.argv[1]}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
