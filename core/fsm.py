import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional
import traceback

from loguru import logger


@dataclass(frozen=True)
class State:
    """Иммутабельное состояние FSM с изолированной памятью."""
    current_state: str
    entered_at: float
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "current_state": self.current_state,
            "entered_at": self.entered_at,
            "context": self.context
        }

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        return cls(
            current_state=data["current_state"],
            entered_at=data["entered_at"],
            context=data.get("context", {})
        )


@dataclass(frozen=True)
class Transition:
    from_state: str
    to_state: str
    trigger: str
    guard: Optional[str] = None
    action: Optional[str] = None
    timeout_sec: Optional[float] = None
    internal: bool = False  # Если True, состояние не меняется и таймеры не сбрасываются


@dataclass(frozen=True)
class FSMDefinition:
    entity_id: str
    initial_state: str
    states: tuple[str, ...]
    transitions: tuple[Transition, ...]
    debounce_sec: float = 0.0


class FSMPersistence:
    """Сохраняет состояния FSM на диск, чтобы пережить перезапуск HA."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, State]:
        if not self.storage_path.exists():
            return {}
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: State.from_dict(v) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to load FSM states from disk: {e}")
            return {}

    def save(self, states: dict[str, State]) -> None:
        try:
            data = {k: v.to_dict() for k, v in states.items()}
            # Пишем атомарно через temp файл, чтобы не повредить JSON при сбое питания
            temp_path = self.storage_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self.storage_path)
        except Exception as e:
            logger.error(f"Failed to save FSM states to disk: {e}")


class FSMEngine:
    def __init__(self, persistence: Optional[FSMPersistence] = None) -> None:
        self._states: dict[str, State] = {}
        self._definitions: dict[str, FSMDefinition] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._last_transition_time: dict[str, float] = {}

        # Реестры бизнес-логики
        self._guards: dict[str, Callable[[State, dict], bool]] = {}
        self._actions: dict[str, Callable[[State, dict], dict]] = {}

        # Метрики
        self._stats: dict[str, dict[str, int]] = {}  # entity_id -> {transition_name: count}

        self._persistence = persistence or FSMPersistence(Path(".fsm_states.json"))
        self._states = self._persistence.load()
        logger.info(f"FSM Engine initialized. Loaded {len(self._states)} states from disk.")

    def register_definition(self, definition: FSMDefinition) -> None:
        """Регистрирует автомат с предварительной валидацией графа."""
        self._validate_definition(definition)
        self._definitions[definition.entity_id] = definition

        if definition.entity_id not in self._states:
            self._states[definition.entity_id] = State(
                current_state=definition.initial_state,
                entered_at=time.time(),
                context={}
            )
            self._persistence.save(self._states)

        self._stats.setdefault(definition.entity_id, {})
        logger.debug(f"Registered FSM for {definition.entity_id}")

    def _validate_definition(self, defn: FSMDefinition) -> None:
        """Проверяет, что граф состояний не содержит битых ссылок."""
        if defn.initial_state not in defn.states:
            raise ValueError(f"Initial state '{defn.initial_state}' not in states list for {defn.entity_id}")

        for t in defn.transitions:
            if t.from_state not in defn.states:
                raise ValueError(f"Transition from unknown state '{t.from_state}' in {defn.entity_id}")
            if not t.internal and t.to_state not in defn.states:
                raise ValueError(f"Transition to unknown state '{t.to_state}' in {defn.entity_id}")

    def register_guard(self, name: str, guard_fn: Callable[[State, dict], bool]) -> None:
        self._guards[name] = guard_fn

    def register_action(self, name: str, action_fn: Callable[[State, dict], dict]) -> None:
        self._actions[name] = action_fn

    def get_state(self, entity_id: str) -> Optional[State]:
        return self._states.get(entity_id)

    def get_stats(self, entity_id: str) -> dict[str, int]:
        return self._stats.get(entity_id, {})

    async def _cancel_timers(self, entity_id: str) -> None:
        """Безопасно отменяет таймеры, избегая RuntimeError при self-cancellation."""
        if entity_id in self._timers:
            timer_task = self._timers.pop(entity_id)
            if not timer_task.done():
                timer_task.cancel()
                # Избегаем падения, если задача отменяет сама себя
                if timer_task is not asyncio.current_task():
                    try:
                        await timer_task
                    except asyncio.CancelledError:
                        pass

    def _evaluate_guard(self, guard_name: Optional[str], state: State, ctx: dict) -> bool:
        if not guard_name:
            return True
        guard_fn = self._guards.get(guard_name)
        if not guard_fn:
            logger.warning(f"Guard '{guard_name}' not found in registry")
            return True

        try:
            return bool(guard_fn(state, ctx))
        except Exception as e:
            # Изоляция: упавший guard не должен ломать весь движок
            logger.error(f"Guard '{guard_name}' crashed: {e}\n{traceback.format_exc()}")
            return False

    async def _execute_action(self, action_name: Optional[str], state: State, ctx: dict) -> dict:
        if not action_name:
            return {}
        action_fn = self._actions.get(action_name)
        if not action_fn:
            logger.warning(f"Action '{action_name}' not found in registry")
            return {}

        try:
            result = action_fn(state, ctx)
            if asyncio.iscoroutine(result):
                result = await result

            # Action возвращает словарь-патч для обновления памяти автомата
            return result if isinstance(result, dict) else {}
        except Exception as e:
            # Изоляция: упавший action (например, битый запрос в HA) не валит FSM
            logger.error(f"Action '{action_name}' crashed: {e}\n{traceback.format_exc()}")
            return {}

    async def trigger(self, entity_id: str, event: str, external_ctx: Optional[dict] = None) -> bool:
        # 1. Отменяем старые таймеры (решает проблему утечек)
        await self._cancel_timers(entity_id)

        definition = self._definitions.get(entity_id)
        if not definition:
            logger.warning(f"Trigger '{event}' for unknown entity {entity_id}")
            return False

        current_state = self._states.get(entity_id)
        if not current_state:
            return False

        now = time.time()
        external_ctx = external_ctx or {}

        # Debounce (защита от дребезга контактов)
        last_time = self._last_transition_time.get(entity_id, 0)
        if definition.debounce_sec > 0 and (now - last_time) < definition.debounce_sec:
            logger.debug(f"Ignoring '{event}' for {entity_id} due to debounce")
            return False

        # Ищем подходящие переходы
        matching_transitions = [
            t for t in definition.transitions
            if t.from_state == current_state.current_state and t.trigger == event
        ]

        for transition in matching_transitions:
            # Проверяем условие
            if not self._evaluate_guard(transition.guard, current_state, external_ctx):
                continue

            # Выполняем действие (с изоляцией ошибок)
            ctx_patch = await self._execute_action(transition.action, current_state, external_ctx)

            # Обновляем статистику
            trans_name = f"{transition.from_state}->{transition.to_state}_{event}"
            self._stats[entity_id][trans_name] = self._stats[entity_id].get(trans_name, 0) + 1

            if transition.internal:
                # Internal transition: состояние не меняется, таймеры не сбрасываются
                # Но мы обновляем контекст (память автомата)
                new_context = {**current_state.context, **ctx_patch}
                self._states[entity_id] = State(
                    current_state=current_state.current_state,
                    entered_at=current_state.entered_at,
                    context=new_context
                )
                self._persistence.save(self._states)
                logger.debug(f"Entity {entity_id}: Internal transition '{event}'")
                return True

            # Обычный переход: меняем состояние
            new_context = {**current_state.context, **ctx_patch}
            new_state = State(
                current_state=transition.to_state,
                entered_at=now,
                context=new_context
            )
            self._states[entity_id] = new_state
            self._last_transition_time[entity_id] = now
            self._persistence.save(self._states)

            logger.info(f"Entity {entity_id}: {current_state.current_state} -> {transition.to_state} (trigger: {event})")

            # Планируем таймер безопасно (через wrapper, чтобы не убить себя)
            if transition.timeout_sec and transition.timeout_sec > 0:
                async def timeout_wrapper(delay=transition.timeout_sec, eid=entity_id):
                    try:
                        await asyncio.sleep(delay)
                        # Запускаем следующий триггер как независимую задачу
                        asyncio.create_task(self.trigger(eid, "timeout"))
                    except asyncio.CancelledError:
                        pass  # Таймер был отменен, это нормально

                self._timers[entity_id] = asyncio.create_task(timeout_wrapper())

            return True

        logger.debug(f"No matching transition for {entity_id} in state '{current_state.current_state}' on trigger '{event}'")
        return False

    async def shutdown(self) -> None:
        """Корректное завершение работы: отменяем все таймеры и сбрасываем на диск."""
        logger.info("Shutting down FSM Engine...")
        for entity_id in list(self._timers.keys()):
            await self._cancel_timers(entity_id)
        self._persistence.save(self._states)
        logger.info("FSM Engine shutdown complete.")
