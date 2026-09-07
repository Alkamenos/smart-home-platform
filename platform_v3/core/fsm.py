"""
Core FSM Engine - Универсальный движок конечных автоматов

Ключевые принципы:
- Нет eval() - guard условия через функции (type-safe)
- Иммутабельность - состояния не мутируются, создаются новые
- Event-driven - все переходы через Event Bus
- Простота - минимум абстракций (~200 строк кода)
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Transition:
    """Описание перехода между состояниями"""
    
    from_state: str | tuple[str, ...]  # Из какого состояния ("*" = из любого)
    to_state: str                      # В какое состояние
    trigger: str                       # Событие, вызывающее переход
    guard: Callable[[dict], bool] = lambda ctx: True  # Условие
    priority: int = 0                  # Приоритет (выше = важнее)
    reason: str = ""                   # Описание


@dataclass(frozen=True)
class FSMDefinition:
    """Описание автомата"""
    
    entity_id: str                     # ID устройства
    states: tuple[str, ...]            # Все возможные состояния
    initial: str                       # Начальное состояние
    transitions: tuple[Transition, ...]  # Все переходы


@dataclass(frozen=True)
class State:
    """Текущее состояние автомата"""
    
    entity_id: str
    current: str
    entered_at: float
    entered_by: str
    entered_why: str
    history: tuple[dict, ...] = field(default_factory=tuple)  # Последние 20 переходов


class FSMEngine:
    """
    Движок конечных автоматов
    
    Usage:
        fsm = FSMEngine(event_bus, logger)
        fsm.register(definition)
        fsm.trigger("light.living_room", "turn_on", {"some": "context"})
    """
    
    def __init__(self, event_bus, logger):
        self._event_bus = event_bus
        self._logger = logger
        self._definitions: dict[str, FSMDefinition] = {}
        self._states: dict[str, State] = {}
    
    def register(self, definition: FSMDefinition) -> None:
        """Зарегистрировать автомат"""
        self._definitions[definition.entity_id] = definition
        
        # Инициализируем начальное состояние
        if definition.entity_id not in self._states:
            self._states[definition.entity_id] = State(
                entity_id=definition.entity_id,
                current=definition.initial,
                entered_at=time.time(),
                entered_by="init",
                entered_why="Initial state",
                history=()
            )
        
        self._logger.info(
            f"Registered FSM for {definition.entity_id}",
            entity_id=definition.entity_id,
            initial_state=definition.initial,
            transitions_count=len(definition.transitions)
        )
    
    def get_state(self, entity_id: str) -> State | None:
        """Получить текущее состояние автомата"""
        return self._states.get(entity_id)
    
    def trigger(self, entity_id: str, trigger: str, context: dict = None) -> bool:
        """
        Вызвать триггер для автомата
        
        Returns:
            True если переход произошёл, False иначе
        """
        context = context or {}
        
        if entity_id not in self._definitions:
            self._logger.error(f"FSM not found for {entity_id}", entity_id=entity_id)
            return False
        
        definition = self._definitions[entity_id]
        current_state = self._states[entity_id]
        
        # Находим подходящие переходы
        matching_transitions = []
        for transition in definition.transitions:
            if transition.trigger != trigger:
                continue
            
            # Проверяем from_state
            if transition.from_state != "*":
                if isinstance(transition.from_state, tuple):
                    if current_state.current not in transition.from_state:
                        continue
                else:
                    if current_state.current != transition.from_state:
                        continue
            
            # Проверяем guard условие
            try:
                if not transition.guard(context):
                    continue
            except Exception as e:
                self._logger.error(
                    f"Guard failed for {entity_id}: {e}",
                    entity_id=entity_id,
                    trigger=trigger,
                    error=str(e)
                )
                continue
            
            matching_transitions.append(transition)
        
        if not matching_transitions:
            self._logger.debug(
                f"No matching transition for {trigger} in {current_state.current}",
                entity_id=entity_id,
                trigger=trigger,
                current_state=current_state.current
            )
            return False
        
        # Выбираем переход с наивысшим приоритетом
        best_transition = max(matching_transitions, key=lambda t: t.priority)
        
        # Выполняем переход
        return self._execute_transition(entity_id, best_transition, context)
    
    def _execute_transition(self, entity_id: str, transition: Transition, context: dict) -> bool:
        """Выполнить переход"""
        old_state = self._states[entity_id]
        now = time.time()
        
        # Обновляем историю
        history_entry = {
            "from": old_state.current,
            "to": transition.to_state,
            "trigger": transition.trigger,
            "why": transition.reason,
            "at": now
        }
        new_history = (history_entry,) + old_state.history[:19]  # Храним последние 20
        
        # Создаём новое состояние (иммутабельность)
        new_state = State(
            entity_id=entity_id,
            current=transition.to_state,
            entered_at=now,
            entered_by=transition.trigger,
            entered_why=transition.reason,
            history=new_history
        )
        
        # Обновляем состояние
        self._states[entity_id] = new_state
        
        # Публикуем событие
        self._event_bus.publish("fsm.transition", {
            "entity_id": entity_id,
            "from_state": old_state.current,
            "to_state": transition.to_state,
            "trigger": transition.trigger,
            "reason": transition.reason,
            "duration_ms": int((now - old_state.entered_at) * 1000) if old_state.entered_at < now else 0
        })
        
        self._logger.info(
            f"Transition: {old_state.current} -> {transition.to_state}",
            entity_id=entity_id,
            from_state=old_state.current,
            to_state=transition.to_state,
            trigger=transition.trigger,
            reason=transition.reason
        )
        
        return True
    
    def reset(self, entity_id: str) -> bool:
        """Сбросить автомат в начальное состояние"""
        if entity_id not in self._definitions:
            return False
        
        definition = self._definitions[entity_id]
        old_state = self._states[entity_id]
        now = time.time()
        
        # Добавляем запись в историю
        history_entry = {
            "from": old_state.current,
            "to": definition.initial,
            "trigger": "reset",
            "why": "Manual reset",
            "at": now
        }
        new_history = (history_entry,) + old_state.history[:19]
        
        self._states[entity_id] = State(
            entity_id=entity_id,
            current=definition.initial,
            entered_at=now,
            entered_by="reset",
            entered_why="Manual reset",
            history=new_history
        )
        
        self._logger.info(
            f"Reset FSM to {definition.initial}",
            entity_id=entity_id,
            previous_state=old_state.current
        )
        
        return True
    
    def get_all_states(self) -> dict[str, State]:
        """Получить снимок всех состояний"""
        return dict(self._states)
