"""
Context Manager - Управление контекстом для FSM

Этот компонент автоматически обновляет контекст FSM на основе:
1. Состояний сенсоров HA (движение, освещенность, температура)
2. Времени суток (расписания, ночь/день)
3. Пользовательских условий (отпуск, гости и т.д.)

Usage:
    context_manager = ContextManager(event_bus, fsm_engine, logger)
    context_manager.subscribe_sensor("binary_sensor.living_room_motion", "living_room_motion_sensor")
    context_manager.schedule_time_check("living_room_is_schedule_time", "07:00", "23:00")
    
    # Автоматически обновляет контекст и триггерит FSM при изменениях
"""

from __future__ import annotations
import time
from typing import Callable, Optional
from dataclasses import dataclass


@dataclass
class TimeRange:
    """Диапазон времени для расписания"""
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    
    @classmethod
    def from_string(cls, time_str: str) -> "TimeRange":
        """Создать из строки 'HH:MM'"""
        parts = time_str.split(":")
        return cls(int(parts[0]), int(parts[1]), 0, 0)
    
    def is_within(self, hour: int, minute: int) -> bool:
        """Проверить попадает ли время в диапазон"""
        current_minutes = hour * 60 + minute
        start_minutes = self.start_hour * 60 + self.start_minute
        end_minutes = self.end_hour * 60 + self.end_minute
        
        if start_minutes <= end_minutes:
            return start_minutes <= current_minutes <= end_minutes
        else:
            # Переход через полночь (например, 22:00 - 06:00)
            return current_minutes >= start_minutes or current_minutes <= end_minutes


class ContextManager:
    """
    Менеджер контекста для FSM
    
    Автоматически обновляет контекст на основе событий HA
    и триггерит FSM при изменениях.
    """
    
    def __init__(self, event_bus, fsm_engine, logger):
        self._event_bus = event_bus
        self._fsm_engine = fsm_engine
        self._logger = logger
        
        # Контекст по комнатам/зонам
        self._context: dict[str, dict] = {}
        
        # Подписки на сенсоры: entity_id -> context_key
        self._sensor_subscriptions: dict[str, str] = {}
        
        # Расписания: context_key -> TimeRange
        self._schedules: dict[str, TimeRange] = {}
        
        # Таймер для периодической проверки расписаний
        self._schedule_check_interval = 60  # секунд
        
        # Подписываемся на события HA
        event_bus.subscribe("ha.state_changed", self._on_ha_state_change)
        event_bus.subscribe("platform.started", self._on_platform_started)
        
        self._logger.info("ContextManager initialized")
    
    def _on_platform_started(self, data: dict) -> None:
        """При старте платформы запускаем проверку расписаний"""
        self._start_schedule_checker()
    
    def _on_ha_state_change(self, data: dict) -> None:
        """
        Обработчик изменения состояния сенсора
        
        Args:
            data: {
                "entity_id": "binary_sensor.living_room_motion",
                "old_state": "off",
                "new_state": "on"
            }
        """
        entity_id = data.get("entity_id")
        new_state = data.get("new_state")
        
        if entity_id in self._sensor_subscriptions:
            context_key = self._sensor_subscriptions[entity_id]
            
            # Конвертируем состояние HA в boolean
            value = self._ha_state_to_bool(new_state)
            
            # Обновляем контекст
            old_value = self._context.get(context_key, False)
            self._context[context_key] = value
            
            self._logger.debug(
                f"Context updated: {context_key} = {value}",
                context_key=context_key,
                old_value=old_value,
                new_value=value,
                entity_id=entity_id
            )
            
            # Триггерим обновление для всех автоматов которые используют этот контекст
            self._trigger_affected_fsms(context_key, value)
    
    def _ha_state_to_bool(self, state: str) -> bool:
        """Преобразует состояние HA в boolean"""
        if state is None:
            return False
        state_lower = str(state).lower()
        return state_lower in ("on", "open", "active", "home", "true", "yes")
    
    def subscribe_sensor(self, entity_id: str, context_key: str) -> None:
        """
        Подписаться на изменения сенсора
        
        Args:
            entity_id: ID сенсора в HA (например, "binary_sensor.motion_living_room")
            context_key: Ключ контекста (например, "living_room_motion_sensor")
        """
        self._sensor_subscriptions[entity_id] = context_key
        self._logger.info(
            f"Subscribed sensor {entity_id} to context key {context_key}"
        )
    
    def subscribe_schedule(self, context_key: str, start: str, end: str) -> None:
        """
        Подписаться на временной диапазон
        
        Args:
            context_key: Ключ контекста (например, "living_room_is_schedule_time")
            start: Время начала в формате "HH:MM"
            end: Время окончания в формате "HH:MM"
        """
        # Парсим время начала и конца
        start_parts = start.split(":")
        end_parts = end.split(":")
        
        time_range = TimeRange(
            start_hour=int(start_parts[0]),
            start_minute=int(start_parts[1]),
            end_hour=int(end_parts[0]),
            end_minute=int(end_parts[1])
        )
        
        self._schedules[context_key] = time_range
        
        # Сразу обновляем контекст
        self._update_schedule_context(context_key, time_range)
        
        self._logger.info(
            f"Subscribed schedule {context_key}: {start} - {end}"
        )
    
    def _update_schedule_context(self, context_key: str, time_range: TimeRange) -> None:
        """Обновить контекст для расписания"""
        now = time.localtime()
        is_active = time_range.is_within(now.tm_hour, now.tm_min)
        
        old_value = self._context.get(context_key, False)
        self._context[context_key] = is_active
        
        if old_value != is_active:
            self._logger.info(
                f"Schedule updated: {context_key} = {is_active}",
                context_key=context_key,
                is_active=is_active,
                current_time=f"{now.tm_hour:02d}:{now.tm_min:02d}"
            )
            self._trigger_affected_fsms(context_key, is_active)
    
    def _start_schedule_checker(self) -> None:
        """Запустить периодическую проверку расписаний"""
        import asyncio
        
        async def check_schedules():
            while True:
                try:
                    await asyncio.sleep(self._schedule_check_interval)
                    for context_key, time_range in self._schedules.items():
                        self._update_schedule_context(context_key, time_range)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._logger.error(f"Schedule checker error: {e}")
        
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(check_schedules())
            self._logger.info("Schedule checker started")
        except RuntimeError:
            self._logger.warning("No running event loop, schedule checker not started")
    
    def set_context(self, key: str, value) -> None:
        """
        Установить значение контекста вручную
        
        Args:
            key: Ключ контекста
            value: Значение
        """
        old_value = self._context.get(key)
        self._context[key] = value
        
        self._logger.debug(
            f"Context manually set: {key} = {value}",
            context_key=key,
            old_value=old_value,
            new_value=value
        )
        
        self._trigger_affected_fsms(key, value)
    
    def get_context(self, key: str, default=None):
        """Получить значение контекста"""
        return self._context.get(key, default)
    
    def get_all_context(self) -> dict:
        """Получить весь контекст"""
        return dict(self._context)
    
    def _trigger_affected_fsms(self, context_key: str, value) -> None:
        """
        Триггерить автоматы которые зависят от этого контекста
        
        Это сложная задача - нужно найти все FSM у которых есть guard условия
        использующие этот ключ контекста. Для простоты мы публикуем событие
        о изменении контекста, а внешние обработчики могут решить какие FSM
        нужно обновить.
        """
        self._event_bus.publish("context.changed", {
            "key": context_key,
            "value": value,
            "timestamp": time.time()
        })
        
        # В реальной реализации здесь был бы маппинг context_key -> entity_ids
        # и вызов fsm.trigger() для каждого автомата с новым контекстом
