#!/usr/bin/env python3
"""
FSM Engine V2 — универсальный движок конечных автоматов.

Ключевые отличия от V1:
- Поддержка guard условий (вычисление через eval)
- Type-safe определения через dataclasses
- Встроенная история переходов
- Поддержка контекста для принятия решений
"""
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime

@dataclass
class FSMState:
    """Текущее состояние автомата"""
    entity_id: str
    state: str
    entered_at: str
    entered_by: str
    entered_why: str
    history: list[dict] = field(default_factory=list)

@dataclass
class FSMDefinition:
    """Описание автомата"""
    states: list[str]
    initial: str
    transitions: list[dict] = field(default_factory=list)
    debounce_sec: float = 0.0
    debounce_exempt: set[str] = field(default_factory=lambda: {"manual_change", "timeout", "device_unavailable"})

class FSMEngine:
    """Универсальный движок конечных автоматов"""
    
    def __init__(self):
        self._states: dict[str, FSMState] = {}
        self._definitions: dict[str, FSMDefinition] = {}
        self._last_transition: dict[str, float] = {}
        self._history_max = 20
    
    def register(self, entity_id: str, definition: FSMDefinition):
        """Зарегистрировать автомат"""
        self._definitions[entity_id] = definition
        
        if entity_id not in self._states:
            self._states[entity_id] = FSMState(
                entity_id=entity_id,
                state=definition.initial,
                entered_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                entered_by="init",
                entered_why="Инициализация при старте"
            )
    
    def get_state(self, entity_id: str) -> Optional[str]:
        """Получить текущее состояние"""
        entry = self._states.get(entity_id)
        return entry.state if entry else None
    
    @staticmethod
    def _normalize_guard(guard: str) -> str:
        """Нормализовать guard: AND -> and, OR -> or, NOT -> not"""
        result = guard
        # Заменяем логические операторы на питоновские
        result = result.replace(" AND ", " and ")
        result = result.replace(" OR ", " or ")
        result = result.replace(" NOT ", " not ")
        return result
    
    def _evaluate_guard(self, guard: str, ctx: dict) -> bool:
        """Вычислить guard условие в контексте"""
        if not guard:
            return True
        try:
            normalized = self._normalize_guard(guard)
            return bool(eval(normalized, {"__builtins__": {}}, ctx))
        except Exception:
            return False
    
    def trigger(self, entity_id: str, trigger: str, src: str = "автоматика", 
                ctx: Optional[dict] = None) -> bool:
        """
        Обработать триггер: найти переход, сменить состояние.
        
        Ключевое отличие: вычисляет guard условия!
        """
        definition = self._definitions.get(entity_id)
        if not definition:
            return False
        
        current_state = self.get_state(entity_id)
        candidates = []
        
        for t in definition.transitions:
            if t.get("trigger") != trigger:
                continue
            
            from_states = t.get("from", [])
            if isinstance(from_states, str):
                from_states = [from_states]
            
            if "*" not in from_states and current_state not in from_states:
                continue
            
            # Вычисляем guard условие
            guard = t.get("guard")
            if not self._evaluate_guard(guard, ctx or {}):
                continue
            
            candidates.append(t)
        
        if not candidates:
            return False
        
        # Сортируем по приоритету и берем лучший
        candidates.sort(key=lambda t: t.get("priority", 0), reverse=True)
        best = candidates[0]
        
        target_state = best.get("to")
        
        # Поддержка псевдонима PREVIOUS
        if target_state == "PREVIOUS":
            history = self._states[entity_id].history
            if history:
                target_state = history[0].get("from", definition.initial)
            else:
                target_state = definition.initial
        
        if target_state not in definition.states or target_state == current_state:
            return False
        
        # Debounce
        now = time.monotonic()
        cooldown = definition.debounce_sec
        if cooldown > 0 and trigger not in definition.debounce_exempt:
            last = self._last_transition.get(entity_id)
            if last is not None and now - last < cooldown:
                return False
        
        # Выполняем переход
        self._last_transition[entity_id] = now
        self._set_state(entity_id, target_state, trigger, best.get("why", ""), src)
        return True
    
    def _set_state(self, entity_id: str, new_state: str, trigger: str, 
                   why: str, src: str):
        """Внутренний метод смены состояния"""
        entry = self._states.get(entity_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if entry:
            old_state = entry.state
            history_entry = {
                "time": now_str,
                "from": old_state,
                "to": new_state,
                "trigger": trigger,
                "why": why,
                "src": src
            }
            entry.history.insert(0, history_entry)
            if len(entry.history) > self._history_max:
                entry.history = entry.history[:self._history_max]
            
            entry.state = new_state
            entry.entered_at = now_str
            entry.entered_by = trigger
            entry.entered_why = why
    
    def get_history(self, entity_id: str, limit: int = 5) -> list[dict]:
        """Получить историю переходов"""
        entry = self._states.get(entity_id)
        return entry.history[:limit] if entry else []
    
    def debug(self, entity_id: str = None) -> dict:
        """Диагностика автоматов"""
        result = {}
        targets = [entity_id] if entity_id else list(self._states.keys())
        
        for eid in targets:
            entry = self._states.get(eid)
            definition = self._definitions.get(eid)
            
            if not entry:
                result[eid] = {"error": "not registered"}
                continue
            
            result[eid] = {
                "state": entry.state,
                "entered_at": entry.entered_at,
                "entered_by": entry.entered_by,
                "entered_why": entry.entered_why,
                "history": entry.history[:5],
                "transitions_count": len(definition.transitions) if definition else 0
            }
        
        return result

# Глобальный экземпляр движка
FSM = FSMEngine()
