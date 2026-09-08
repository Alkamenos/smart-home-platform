"""
Control Tracker - Отслеживание кто и когда управлял устройствами

Компонент для отслеживания источников управления:
- manual (пользователь вручную)
- automation (автоматика платформы)
- schedule (расписание)
- external (внешняя система - голосовой помощник, сценарий)
- system (системный - таймаут, восстановление)

Вопросы на которые может ответить:
- Кто последний управлял светом?
- Как давно было ручное вмешательство?
- Сколько раз автоматика срабатывала за день?
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict


@dataclass(frozen=True)
class ControlEvent:
    """Событие управления устройством"""
    entity_id: str
    source: str  # TriggerSource
    trigger: str
    timestamp: float
    value: Optional[str] = None
    
    @property
    def is_manual(self) -> bool:
        """Проверить было ли управление ручным"""
        return self.source == TriggerSource.MANUAL
    
    @property
    def is_automation(self) -> bool:
        """Проверить было ли управление автоматикой"""
        return self.source == TriggerSource.AUTOMATION


class TriggerSource:
    """Стандартные источники триггеров"""
    MANUAL = "manual"         # Пользователь вручную
    AUTOMATION = "automation" # Автоматика платформы
    SCHEDULE = "schedule"     # Расписание
    EXTERNAL = "external"     # Внешняя система (голосовой помощник, сценарий)
    SYSTEM = "system"         # Системный (таймаут, восстановление)


class ControlTracker:
    """
    Отслеживает кто управлял устройствами.
    
    Usage:
        tracker = ControlTracker(history_size=100)
        tracker.record("light.kitchen", TriggerSource.MANUAL, "turn_on")
        
        last_manual = tracker.get_last_manual("light.kitchen")
        if last_manual and last_manual.timestamp > time.time() - 3600:
            print("Ручное управление было в течение последнего часа")
    """
    
    def __init__(self, history_size: int = 100):
        self._history: Dict[str, List[ControlEvent]] = defaultdict(list)
        self._history_size = history_size
        
        # Кэш последних событий для быстрого доступа
        self._last_manual: Dict[str, Optional[ControlEvent]] = {}
        self._last_control: Dict[str, Optional[ControlEvent]] = {}
        
        # Статистика по источникам
        self._stats: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    
    def record(
        self,
        entity_id: str,
        source: str,
        trigger: str,
        value: Optional[str] = None
    ) -> None:
        """
        Записать событие управления.
        
        Args:
            entity_id: ID устройства
            source: Источник управления (TriggerSource.*)
            trigger: Тип триггера
            value: Значение (опционально)
        """
        now = time.time()
        event = ControlEvent(
            entity_id=entity_id,
            source=source,
            trigger=trigger,
            timestamp=now,
            value=value
        )
        
        # Добавляем в историю
        history = self._history[entity_id]
        history.append(event)
        
        # Обрезаем историю если превышает лимит
        if len(history) > self._history_size:
            history.pop(0)
        
        # Обновляем кэш последних событий
        if source == TriggerSource.MANUAL:
            self._last_manual[entity_id] = event
        
        self._last_control[entity_id] = event
        
        # Обновляем статистику
        self._stats[entity_id][source] += 1
    
    def get_last_manual(self, entity_id: str) -> Optional[ControlEvent]:
        """
        Получить последнее ручное вмешательство.
        
        Args:
            entity_id: ID устройства
        
        Returns:
            ControlEvent или None если не было ручных вмешательств
        """
        return self._last_manual.get(entity_id)
    
    def get_last_control(self, entity_id: str) -> Optional[ControlEvent]:
        """
        Получить последнее управление (любой источник).
        
        Args:
            entity_id: ID устройства
        
        Returns:
            ControlEvent или None
        """
        return self._last_control.get(entity_id)
    
    def get_stats(self, entity_id: str) -> dict:
        """
        Получить статистику управлений по источникам.
        
        Args:
            entity_id: ID устройства
        
        Returns:
            dict {source: count}
        """
        stats = self._stats.get(entity_id, {})
        return dict(stats)
    
    def get_history(self, entity_id: str, limit: int = 10) -> List[ControlEvent]:
        """
        Получить историю событий для устройства.
        
        Args:
            entity_id: ID устройства
            limit: Максимальное количество событий
        
        Returns:
            Список ControlEvent (от новых к старым)
        """
        history = self._history.get(entity_id, [])
        return list(reversed(history[-limit:]))
    
    def minutes_since_manual(self, entity_id: str) -> Optional[float]:
        """
        Получить сколько минут прошло с последнего ручного вмешательства.
        
        Args:
            entity_id: ID устройства
        
        Returns:
            Минуты или None если не было ручных вмешательств
        """
        last_manual = self.get_last_manual(entity_id)
        if last_manual is None:
            return None
        
        return (time.time() - last_manual.timestamp) / 60.0
    
    def was_manual_within(self, entity_id: str, minutes: float) -> bool:
        """
        Проверить было ли ручное вмешательство в последние N минут.
        
        Args:
            entity_id: ID устройства
            minutes: Период в минутах
        
        Returns:
            True если было ручное вмешательство
        """
        mins = self.minutes_since_manual(entity_id)
        if mins is None:
            return False
        
        return mins < minutes
    
    def clear(self, entity_id: str = None) -> None:
        """
        Очистить историю.
        
        Args:
            entity_id: ID устройства (None для очистки всех)
        """
        if entity_id:
            self._history.pop(entity_id, None)
            self._last_manual.pop(entity_id, None)
            self._last_control.pop(entity_id, None)
            self._stats.pop(entity_id, None)
        else:
            self._history.clear()
            self._last_manual.clear()
            self._last_control.clear()
            self._stats.clear()
