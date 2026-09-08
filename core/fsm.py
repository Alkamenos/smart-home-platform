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
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, Any
from collections import defaultdict


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
    action: Optional[Callable[[dict], None]] = None  # Действие при выполнении перехода
    cooldown_sec: float = 0.0          # Мин. время после предыдущего перехода (защита от циклов)
    manual_lockout_min: float = 0.0    # Блокировка автоматики после ручного (мин)


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


class Scheduler:
    """
    Неблокирующий планировщик таймеров
    
    Usage:
        scheduler = Scheduler(event_bus, logger)
        scheduler.schedule(entity_id, "timeout", delay_sec=60)
    """
    
    def __init__(self, event_bus, logger):
        self._event_bus = event_bus
        self._logger = logger
        self._timers: Dict[str, asyncio.Task] = {}
        self._pending_callbacks: Dict[str, Callable] = {}
    
    def schedule(self, entity_id: str, trigger: str, delay_sec: int, context: dict = None) -> None:
        """
        Запланировать триггер с задержкой
        
        Args:
            entity_id: ID автомата
            trigger: Тип триггера
            delay_sec: Задержка в секундах
            context: Контекст для триггера
        """
        timer_key = f"{entity_id}:{trigger}"
        
        # Отменяем предыдущий таймер если есть
        if timer_key in self._timers:
            self._timers[timer_key].cancel()
            self._logger.debug(f"Cancelled previous timer for {timer_key}")
        
        context = context or {}
        
        async def delayed_trigger():
            await asyncio.sleep(delay_sec)
            self._logger.debug(
                f"Timer expired for {entity_id}, triggering {trigger}",
                entity_id=entity_id,
                trigger=trigger,
                delay_sec=delay_sec
            )
            # Публикуем событие вместо прямого вызова fsm.trigger
            self._event_bus.publish("fsm.timeout", {
                "entity_id": entity_id,
                "trigger": trigger,
                "context": context
            })
        
        # Создаём задачу в фоне (не блокирует основной поток)
        try:
            task = asyncio.create_task(delayed_trigger())
            self._timers[timer_key] = task
            self._logger.info(
                f"Scheduled timer for {entity_id} in {delay_sec}s",
                entity_id=entity_id,
                trigger=trigger,
                delay_sec=delay_sec
            )
        except RuntimeError as e:
            # Если нет running event loop (синхронный контекст)
            self._logger.warning(
                f"No running event loop, cannot schedule timer: {e}",
                entity_id=entity_id,
                trigger=trigger
            )
            # В синхронном контексте просто публикуем событие сразу
            # Это fallback для тестов и CLI
            self._event_bus.publish("fsm.timeout", {
                "entity_id": entity_id,
                "trigger": trigger,
                "context": context,
                "_immediate": True  # Флаг что сработало немедленно
            })
    
    def cancel(self, entity_id: str, trigger: str = None) -> None:
        """
        Отменить все таймеры для автомата
        
        Args:
            entity_id: ID автомата
            trigger: Конкретный триггер (опционально)
        """
        if trigger:
            timer_key = f"{entity_id}:{trigger}"
            if timer_key in self._timers:
                self._timers[timer_key].cancel()
                del self._timers[timer_key]
                self._logger.debug(f"Cancelled timer {timer_key}")
        else:
            # Отменяем все таймеры для entity_id
            keys_to_cancel = [k for k in self._timers if k.startswith(f"{entity_id}:")]
            for key in keys_to_cancel:
                self._timers[key].cancel()
                del self._timers[key]
            self._logger.debug(f"Cancelled all timers for {entity_id}")
    
    def shutdown(self) -> None:
        """Отменить все таймеры при остановке"""
        for task in self._timers.values():
            task.cancel()
        self._timers.clear()
        self._logger.info("Scheduler shutdown complete")


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
        self._scheduler = Scheduler(event_bus, logger)
        
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
        now = time.time()
        
        # Инициализируем трекер если нужно
        if entity_id not in self._debounce_tracker:
            self._debounce_tracker[entity_id] = {}
        
        tracker = self._debounce_tracker[entity_id]
        last_time = tracker.get(trigger, 0.0)
        
        # Для первого вызова last_time будет 0.0, значит всегда пропускаем
        if last_time == 0.0:
            tracker[trigger] = now
            return True
        
        if now - last_time < debounce_sec:
            return False
        
        # Обновляем время последнего перехода
        tracker[trigger] = now
        return True
    
    def _execute_transition(self, entity_id: str, transition: Transition, context: dict) -> bool:
        """Выполнить переход"""
        old_state = self._states[entity_id]
        now = time.time()
        
        # Выполняем действие перехода если указано (например, сохранение timestamp)
        if transition.action is not None:
            try:
                transition.action(context)
            except Exception as e:
                self._logger.warning(
                    f"Action failed for {entity_id}: {e}",
                    entity_id=entity_id,
                    trigger=transition.trigger,
                    error=str(e)
                )
        
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
        
        # Планируем таймер если указан в переходе
        if transition.timeout_sec is not None and transition.timeout_sec > 0:
            self._scheduler.schedule(
                entity_id=entity_id,
                trigger="timeout",
                delay_sec=transition.timeout_sec,
                context={"from_state": transition.to_state}
            )
        
        # Публикуем событие
        self._event_bus.publish("fsm.transition", {
            "entity_id": entity_id,
            "from_state": old_state.current,
            "to_state": transition.to_state,
            "trigger": transition.trigger,
            "reason": transition.reason,
            "duration_ms": int((now - old_state.entered_at) * 1000) if old_state.entered_at < now else 0,
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
