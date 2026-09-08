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
from typing import Callable, Optional, Dict, Any
from collections import defaultdict
from core.fsm_validator import validate_definition, FSMValidationError
from core.scheduler import BaseScheduler


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
    attributes: dict = field(default_factory=dict)  # Атрибуты для команды (brightness, hvac_mode и т.д.)
    debounce_sec: float = 0.0          # Защита от дребезга (мин. время между переходами)
    cooldown_sec: float = 0.0          # Мин. время после предыдущего перехода (защита от циклов)
    manual_lockout_min: float = 0.0    # Блокировка автоматики после ручного (мин)


@dataclass(frozen=True)
class FSMDefinition:
    """Описание автомата"""
    
    entity_id: str                     # ID устройства
    states: tuple[str, ...]            # Все возможные состояния
    initial: str                       # Начальное состояние
    transitions: tuple[Transition, ...]  # Все переходы
    triggers_mapping: dict[str, str] = field(default_factory=dict)  # Маппинг триггеров: {internal_trigger: ha_entity_id}


@dataclass(frozen=True)
class State:
    """Текущее состояние автомата"""
    
    entity_id: str
    current: str
    entered_at: float                      # Абсолютное время (time.time()) для истории
    entered_by: str
    entered_why: str
    history: tuple[dict, ...] = field(default_factory=tuple)  # Последние 20 переходов
    last_transition_at: float = 0.0        # Монотонное время (time.monotonic()) для cooldown
    last_transition_at_abs: float = 0.0    # Абсолютное время (time.time()) для логов
    manual_override_until: float = 0.0     # Монотонное время (time.monotonic()) для lockout




class FSMEngine:
    """
    Движок конечных автоматов
    
    Usage:
        fsm = FSMEngine(event_bus, logger, scheduler)
        fsm.register(definition)
        fsm.trigger("light.living_room", "turn_on", {"some": "context"})
    """
    
    def __init__(self, event_bus, logger, scheduler: BaseScheduler):
        self._event_bus = event_bus
        self._logger = logger
        self._scheduler = scheduler
        self._definitions: dict[str, FSMDefinition] = {}
        self._states: dict[str, State] = {}
        
        # Debounce tracking: ключ = entity_id, значение = {trigger: last_transition_time}
        self._debounce_tracker: Dict[str, Dict[str, float]] = {}
        
        # Подписываемся на события таймеров
        event_bus.subscribe("fsm.timeout", self._on_timeout_event)
    
    def _on_timeout_event(self, data: dict) -> None:
        """Обработчик событий таймера"""
        entity_id = data.get("entity_id")
        trigger = data.get("trigger")
        context = data.get("context", {})
        
        if entity_id and trigger:
            self._logger.debug(
                f"Processing timeout event for {entity_id}",
                entity_id=entity_id,
                trigger=trigger
            )
            self.trigger(entity_id, trigger, context)
    
    def register(self, definition: FSMDefinition) -> None:
        """Зарегистрировать автомат"""
        # Сначала валидируем определение
        validate_definition(definition)
        
        self._definitions[definition.entity_id] = definition
        
        # Инициализируем начальное состояние
        if definition.entity_id not in self._states:
            now_abs = time.time()          # Абсолютное время для истории
            now_mono = time.monotonic()    # Монотонное время для таймеров
            self._states[definition.entity_id] = State(
                entity_id=definition.entity_id,
                current=definition.initial,
                entered_at=now_abs,
                entered_by="init",
                entered_why="Initial state",
                history=(),
                last_transition_at=0.0,    # 0 означает что cooldown ещё не применялся
                last_transition_at_abs=now_abs,
                manual_override_until=0.0
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
        
        # Проверяем manual_lockout: если сейчас время ручного блокирования, отклоняем автоматические триггеры
        now_mono = time.monotonic()
        if current_state.manual_override_until > now_mono:
            # Это автоматический триггер (не от человека)
            if context.get("source") != "manual":
                remaining_sec = current_state.manual_override_until - now_mono
                self._logger.debug(
                    f"Automatic trigger blocked due to manual lockout",
                    entity_id=entity_id,
                    trigger=trigger,
                    remaining_lockout_sec=remaining_sec
                )
                return False
        
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
            
            # Проверяем cooldown_sec: мин. время после предыдущего перехода (используем монотонное время)
            # last_transition_at инициализируется при регистрации, поэтому проверяем что прошло больше 0 времени
            if transition.cooldown_sec > 0:
                time_since_last = now_mono - current_state.last_transition_at
                if time_since_last <= transition.cooldown_sec:
                    remaining_cooldown = transition.cooldown_sec - time_since_last
                    self._logger.debug(
                        f"Transition skipped due to cooldown",
                        entity_id=entity_id,
                        trigger=trigger,
                        remaining_cooldown_sec=remaining_cooldown
                    )
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
        
        # Проверяем debounce перед выполнением перехода
        if best_transition.debounce_sec > 0:
            if not self._check_debounce(entity_id, trigger, best_transition.debounce_sec):
                self._logger.debug(
                    f"Debounce blocked for {trigger} in {current_state.current}",
                    entity_id=entity_id,
                    trigger=trigger,
                    debounce_sec=best_transition.debounce_sec
                )
                return False
        
        # Выполняем переход
        return self._execute_transition(entity_id, best_transition, context)
    
    def _check_debounce(self, entity_id: str, trigger: str, debounce_sec: float) -> bool:
        """
        Проверить прошло ли время debounce для данного триггера
        
        Args:
            entity_id: ID автомата
            trigger: Тип триггера
            debounce_sec: Минимальное время между переходами (сек)
            
        Returns:
            True если можно выполнить переход, False если слишком рано
        """
        now_mono = time.monotonic()
        
        # Инициализируем трекер если нужно
        if entity_id not in self._debounce_tracker:
            self._debounce_tracker[entity_id] = {}
        
        tracker = self._debounce_tracker[entity_id]
        last_time = tracker.get(trigger, 0.0)
        
        # Для первого вызова last_time будет 0.0, значит всегда пропускаем
        if last_time == 0.0:
            tracker[trigger] = now_mono
            return True
        
        if now_mono - last_time < debounce_sec:
            return False
        
        # Обновляем время последнего перехода
        tracker[trigger] = now_mono
        return True
    
    def _execute_transition(self, entity_id: str, transition: Transition, context: dict) -> bool:
        """Выполнить переход"""
        old_state = self._states[entity_id]
        now_abs = time.time()          # Абсолютное время для истории
        now_mono = time.monotonic()    # Монотонное время для таймеров

        # Публикуем событие команды через EventBus (вместо выполнения action напрямую)
        # Это реализует Dependency Inversion Principle - core не знает об adapters
        self._event_bus.publish("device.command", {
            "entity_id": entity_id,
            "command": transition.trigger,
            "to_state": transition.to_state,
            "attributes": transition.attributes,
            "source": "fsm",
            "reason": transition.reason,
            "timestamp": now_abs
        })

        # Обновляем историю (используем абсолютное время)
        history_entry = {
            "from": old_state.current,
            "to": transition.to_state,
            "trigger": transition.trigger,
            "why": transition.reason,
            "at": now_abs
        }
        new_history = (history_entry,) + old_state.history[:19]  # Храним последние 20
        
        # Определяем новый manual_override_until (используем монотонное время)
        new_manual_override_until = old_state.manual_override_until
        if transition.manual_lockout_min > 0:
            # Если в переходе указан manual_lockout_min, блокируем автоматику
            new_manual_override_until = now_mono + (transition.manual_lockout_min * 60)
        
        # Создаём новое состояние (иммутабельность)
        new_state = State(
            entity_id=entity_id,
            current=transition.to_state,
            entered_at=now_abs,
            entered_by=transition.trigger,
            entered_why=transition.reason,
            history=new_history,
            last_transition_at=now_mono,
            last_transition_at_abs=now_abs,
            manual_override_until=new_manual_override_until
        )
        
        # Обновляем состояние
        self._states[entity_id] = new_state
        
        # Планируем таймер если указан в переходе
        if transition.timeout_sec is not None and transition.timeout_sec > 0:
            self._scheduler.schedule(
                entity_id=entity_id,
                trigger="timeout",
                delay_sec=transition.timeout_sec,
                callback=lambda ctx: self.trigger(entity_id, "timeout", ctx),
                context={"from_state": transition.to_state}
            )
        
        # Публикуем событие (используем абсолютное время для duration calculation)
        self._event_bus.publish("fsm.transition", {
            "entity_id": entity_id,
            "from_state": old_state.current,
            "to_state": transition.to_state,
            "trigger": transition.trigger,
            "reason": transition.reason,
            "duration_ms": int((now_abs - old_state.entered_at) * 1000) if old_state.entered_at < now_abs else 0,
            "attributes": transition.attributes  # Передаём атрибуты для команды
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
        now_abs = time.time()          # Абсолютное время для истории
        now_mono = time.monotonic()    # Монотонное время для таймеров
        
        # Добавляем запись в историю
        history_entry = {
            "from": old_state.current,
            "to": definition.initial,
            "trigger": "reset",
            "why": "Manual reset",
            "at": now_abs
        }
        new_history = (history_entry,) + old_state.history[:19]
        
        self._states[entity_id] = State(
            entity_id=entity_id,
            current=definition.initial,
            entered_at=now_abs,
            entered_by="reset",
            entered_why="Manual reset",
            history=new_history,
            last_transition_at=now_mono,
            last_transition_at_abs=now_abs,
            manual_override_until=0.0
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
