#!/usr/bin/env python3
"""
Feature Base V2 — базовый класс для всех фич платформы.

Каждая фича наследуется от FeatureBase и реализует:
- build_context(): сбор контекста для принятия решений
- decide(): принятие решения на основе контекста
- apply(): применение решения к устройствам (через SyncEngine)
- sync(): синхронизация состояния

Принципы:
- Фича НЕ вызывает напрямую service.call
- Фича возвращает Action, который применяет SyncEngine
- Все изменения логируются с причиной
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from platform_v2.core.room_context import RoomContext
from platform_v2.core.sync_engine import SyncEngine

@dataclass
class Action:
    """Действие, которое нужно применить к устройству"""
    entity_id: str
    state: str  # "on", "off", "heat", "cool", etc.
    attributes: dict = field(default_factory=dict)
    reason: str = ""
    source: str = "automation"

@dataclass
class FeatureDecision:
    """Решение фичи"""
    actions: list[Action] = field(default_factory=list)
    fsm_state: Optional[str] = None
    fsm_why: str = ""
    context_snapshot: dict = field(default_factory=dict)

class FeatureBase(ABC):
    """Базовый класс для всех фич"""
    
    def __init__(self, feature_id: str, config: dict, sync_engine: SyncEngine):
        self._id = feature_id
        self._config = config
        self._sync = sync_engine
        self._enabled = config.get("enabled", True)
    
    @property
    def feature_id(self) -> str:
        return self._id
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @abstractmethod
    def build_context(self, room_context: RoomContext) -> dict:
        """
        Собрать контекст для принятия решений.
        Возвращает словарь с параметрами, специфичными для фичи.
        """
        pass
    
    @abstractmethod
    def decide(self, room_context: RoomContext) -> FeatureDecision:
        """
        Принять решение на основе контекста.
        Возвращает FeatureDecision со списком действий.
        """
        pass
    
    @abstractmethod
    def apply(self, decision: FeatureDecision) -> None:
        """
        Применить решение к устройствам через SyncEngine.
        """
        pass
    
    def sync(self) -> None:
        """Синхронизация состояния (вызывается периодически)"""
        pass
    
    def tick(self, room_context: RoomContext) -> Optional[FeatureDecision]:
        """
        Основной цикл работы фичи. Вызывается каждые N секунд.
        
        1. Собирает контекст
        2. Принимает решение
        3. Применяет решение
        """
        if not self._enabled:
            return None
        
        decision = self.decide(room_context)
        if decision.actions:
            self.apply(decision)
        
        return decision
    
    def get_status(self) -> dict:
        """Получить статус фичи для диагностики"""
        return {
            "feature_id": self._id,
            "enabled": self._enabled,
        }

class FeatureRegistry:
    """Реестр всех фич платформы"""
    
    def __init__(self):
        self._features: dict[str, FeatureBase] = {}
    
    def register(self, feature: FeatureBase) -> None:
        """Зарегистрировать фичу"""
        self._features[feature.feature_id] = feature
    
    def get(self, feature_id: str) -> Optional[FeatureBase]:
        """Получить фичу по ID"""
        return self._features.get(feature_id)
    
    def get_all(self) -> list[FeatureBase]:
        """Получить все фичи"""
        return list(self._features.values())
    
    def get_enabled(self) -> list[FeatureBase]:
        """Получить все включённые фичи"""
        return [f for f in self._features.values() if f.enabled]
    
    def tick_all(self, room_context: RoomContext) -> dict[str, FeatureDecision]:
        """Выполнить цикл для всех включённых фич"""
        results = {}
        for feature in self.get_enabled():
            decision = feature.tick(room_context)
            if decision:
                results[feature.feature_id] = decision
        return results

# Глобальный экземпляр реестра
REGISTRY = FeatureRegistry()
