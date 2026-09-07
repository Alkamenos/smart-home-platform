#!/usr/bin/env python3
"""
Sync Engine V2 - единый источник истины для всех устройств
Заменяет все текущие watchdog и override механизмы
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from datetime import datetime, timedelta

@dataclass
class DesiredState:
    """Желаемое состояние устройства"""
    entity_id: str
    state: str
    attributes: dict = field(default_factory=dict)
    source: str = "automation"
    created_at: float = field(default_factory=time.monotonic)
    expires_at: Optional[float] = None
    
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.monotonic() > self.expires_at

class SyncEngine:
    def __init__(self):
        self._desired_states: Dict[str, DesiredState] = {}
        self._actual_states: Dict[str, dict] = {}
        self._sync_callbacks: Dict[str, Callable] = {}
        self._divergence_since: Dict[str, float] = {}
        
    def set_desired(self, entity_id: str, state: str, attributes: dict = None, 
                    source: str = "automation", duration_min: int = None):
        """Установить желаемое состояние"""
        expires = None
        if duration_min:
            expires = time.monotonic() + duration_min * 60
            
        self._desired_states[entity_id] = DesiredState(
            entity_id=entity_id,
            state=state,
            attributes=attributes or {},
            source=source,
            expires_at=expires
        )
        # Сразу пытаемся применить
        self._apply_state(entity_id)
        
    def _apply_state(self, entity_id: str):
        """Применить желаемое состояние к устройству"""
        desired = self._desired_states.get(entity_id)
        if not desired or desired.is_expired():
            return
            
        # Здесь вызываем service.call для применения состояния
        # Это будет интегрировано с HA
        pass
        
    def sync_tick(self):
        """Один проход синхронизации - вызывается каждые 10 сек"""
        now = time.monotonic()
        
        for entity_id, desired in list(self._desired_states.items()):
            if desired.is_expired():
                del self._desired_states[entity_id]
                continue
                
            actual = self._actual_states.get(entity_id, {})
            
            # Проверяем расхождение
            if desired.state != actual.get("state"):
                if entity_id not in self._divergence_since:
                    self._divergence_since[entity_id] = now
                elif now - self._divergence_since[entity_id] > 30:  # 30 сек
                    # Применяем желаемое состояние
                    self._apply_state(entity_id)
                    self._divergence_since[entity_id] = now
            else:
                self._divergence_since.pop(entity_id, None)
                
    def update_actual(self, entity_id: str, state: str, attributes: dict = None):
        """Обновить реальное состояние (вызывается из HA)"""
        self._actual_states[entity_id] = {
            "state": state,
            "attributes": attributes or {},
            "updated_at": time.monotonic()
        }
        
    def get_status(self) -> dict:
        """Получить статус всех устройств для диагностики"""
        result = {}
        for entity_id in self._desired_states:
            desired = self._desired_states[entity_id]
            actual = self._actual_states.get(entity_id, {})
            result[entity_id] = {
                "desired": desired.state,
                "actual": actual.get("state"),
                "source": desired.source,
                "in_sync": desired.state == actual.get("state"),
                "divergence_sec": time.monotonic() - self._divergence_since.get(entity_id, time.monotonic())
            }
        return result

# Глобальный экземпляр
SYNC = SyncEngine()
