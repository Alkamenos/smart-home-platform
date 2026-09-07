#!/usr/bin/env python3
"""
Sync Engine V2 — автоматическая синхронизация желаемого и реального состояния.

Решает проблему "автомат показывает одно, а устройство другое".

Принципы:
- Желаемое состояние (desired) всегда хранится в платформе
- Реальное состояние (actual) читается из Home Assistant
- Если расхождение длится дольше grace_sec, применяем desired
- Ручное вмешательство блокирует синхронизацию на заданное время
"""
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime

@dataclass
class DesiredState:
    """Желаемое состояние устройства"""
    entity_id: str
    state: str
    attributes: dict = field(default_factory=dict)
    source: str = "automation"  # automation | manual | schedule
    reason: str = ""
    created_at: float = field(default_factory=time.monotonic)
    expires_at: Optional[float] = None
    
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.monotonic() > self.expires_at

@dataclass
class ActualState:
    """Реальное состояние устройства"""
    entity_id: str
    state: str
    attributes: dict = field(default_factory=dict)
    last_updated: float = field(default_factory=time.monotonic)

@dataclass
class Divergence:
    """Расхождение между желаемым и реальным"""
    entity_id: str
    desired: DesiredState
    actual: ActualState
    started_at: float
    resolved_at: Optional[float] = None
    
    @property
    def duration_sec(self) -> float:
        end = self.resolved_at or time.monotonic()
        return end - self.started_at

class SyncEngine:
    """
    Движок синхронизации.
    
    Каждое устройство имеет:
    - desired state (что платформа хочет)
    - actual state (что устройство реально делает)
    - расхождение (если они не совпадают)
    """
    
    def __init__(self, grace_sec: float = 30.0):
        self._desired: dict[str, DesiredState] = {}
        self._actual: dict[str, ActualState] = {}
        self._divergences: dict[str, Divergence] = {}
        self._manual_locks: dict[str, float] = {}  # entity -> unlock_time
        self._grace_sec = grace_sec
        self._apply_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
    
    def set_apply_callback(self, callback: Callable[[str, str, dict], None]):
        """Установить функцию применения состояния к устройству"""
        self._apply_callback = callback
    
    def set_log_callback(self, callback: Callable[[str], None]):
        """Установить функцию логирования"""
        self._log_callback = callback
    
    # ===== Управление желаемым состоянием =====
    
    def set_desired(self, entity_id: str, state: str, attributes: dict = None,
                    source: str = "automation", reason: str = "",
                    duration_min: int = None) -> None:
        """Установить желаемое состояние устройства"""
        expires = None
        if duration_min:
            expires = time.monotonic() + duration_min * 60
        
        self._desired[entity_id] = DesiredState(
            entity_id=entity_id,
            state=state,
            attributes=attributes or {},
            source=source,
            reason=reason,
            expires_at=expires
        )
        
        # Не применяем сразу — ждём синхронизации или обновления реального состояния
        # Это предотвращает гонки и дублирование команд
    
    def get_desired(self, entity_id: str) -> Optional[DesiredState]:
        """Получить желаемое состояние"""
        desired = self._desired.get(entity_id)
        if desired and desired.is_expired():
            del self._desired[entity_id]
            return None
        return desired
    
    def clear_desired(self, entity_id: str) -> None:
        """Очистить желаемое состояние"""
        self._desired.pop(entity_id, None)
        self._divergences.pop(entity_id, None)
    
    # ===== Обновление реального состояния =====
    
    def update_actual(self, entity_id: str, state: str, attributes: dict = None) -> None:
        """Обновить реальное состояние (вызывается из HA)"""
        # Проверяем что state не None и не coroutine
        if state is None:
            return
        if hasattr(state, "__await__"):
            return
        
        state_str = str(state)
        if not state_str or state_str in ("", "None"):
            return
        
        self._actual[entity_id] = ActualState(
            entity_id=entity_id,
            state=state_str,
            attributes=attributes or {},
            last_updated=time.monotonic()
        )
        # Проверяем расхождение
        self._check_divergence(entity_id)
    
    # ===== Ручное вмешательство =====
    
    def set_manual_lock(self, entity_id: str, duration_min: int = 60, reason: str = "") -> None:
        """Заблокировать синхронизацию (ручное вмешательство)"""
        unlock_time = time.monotonic() + duration_min * 60
        self._manual_locks[entity_id] = unlock_time
        self._log(f"[SYNC] {entity_id}: manual lock {duration_min} min ({reason})")
    
    def is_manual_locked(self, entity_id: str) -> bool:
        """Проверить, заблокирована ли синхронизация"""
        unlock_time = self._manual_locks.get(entity_id)
        if unlock_time is None:
            return False
        if time.monotonic() > unlock_time:
            del self._manual_locks[entity_id]
            return False
        return True
    
    def release_manual_lock(self, entity_id: str) -> None:
        """Снять ручную блокировку"""
        self._manual_locks.pop(entity_id, None)
        self._log(f"[SYNC] {entity_id}: manual lock released")
    
    # ===== Основной цикл синхронизации =====
    
    def sync_tick(self) -> list[str]:
        """
        Один проход синхронизации. Вызывается каждые 10 сек.
        Возвращает список применённых состояний.
        """
        applied = []
        now = time.monotonic()
        
        for entity_id in list(self._desired.keys()):
            desired = self._desired.get(entity_id)
            if not desired:
                continue
            
            # Удаляем истёкшие
            if desired.is_expired():
                del self._desired[entity_id]
                self._divergences.pop(entity_id, None)
                continue
            
            # Пропускаем заблокированные
            if self.is_manual_locked(entity_id):
                continue
            
            # Проверяем расхождение
            self._check_divergence(entity_id)
            
            # Если расхождение длится дольше grace — применяем
            divergence = self._divergences.get(entity_id)
            if divergence and divergence.duration_sec >= self._grace_sec:
                if self._try_apply(entity_id):
                    applied.append(entity_id)
                    divergence.resolved_at = time.monotonic()
                    # Не логируем каждое применение — только ошибки
        
        return applied
    
    # ===== Внутренние методы =====
    
    def _check_divergence(self, entity_id: str) -> None:
        """Проверить расхождение между желаемым и реальным"""
        desired = self._desired.get(entity_id)
        actual = self._actual.get(entity_id)
        
        if not desired or not actual:
            return
        
        if desired.state == actual.state:
            # Состояния совпадают — расхождения нет
            self._divergences.pop(entity_id, None)
        else:
            # Есть расхождение
            divergence = self._divergences.get(entity_id)
            
            # Если расхождение длится больше grace_sec — это ручное вмешательство
            if divergence is None:
                divergence = Divergence(
                    entity_id=entity_id,
                    desired=desired,
                    actual=actual,
                    started_at=time.monotonic()
                )
                self._divergences[entity_id] = divergence
            elif divergence.duration_sec > self._grace_sec:
                # Ручное вмешательство — блокируем синхронизацию
                if not self.is_manual_locked(entity_id):
                    self.set_manual_lock(entity_id, duration_min=60, reason="manual change")
                    # Обновляем желаемое состояние на реальное
                    self._desired[entity_id] = DesiredState(
                        entity_id=entity_id,
                        state=actual.state,
                        attributes=actual.attributes,
                        source="manual",
                        reason="Manual change detected"
                    )
                    self._divergences.pop(entity_id, None)
    
    def _try_apply(self, entity_id: str) -> bool:
        """Применить желаемое состояние к устройству"""
        desired = self._desired.get(entity_id)
        if not desired:
            return False
        
        # Не применяем если заблокировано ручным вмешательством
        if self.is_manual_locked(entity_id):
            return False
        
        # Проверяем что состояние ещё не применено
        actual = self._actual.get(entity_id)
        if actual and actual.state == desired.state:
            # Уже синхронизировано
            self._divergences.pop(entity_id, None)
            return False
        
        if self._apply_callback:
            try:
                self._apply_callback(entity_id, desired.state, desired.attributes)
                
                # Обновляем _actual сразу после применения
                self._actual[entity_id] = ActualState(
                    entity_id=entity_id,
                    state=desired.state,
                    attributes=desired.attributes,
                    last_updated=time.monotonic()
                )
                
                # Убираем расхождение
                self._divergences.pop(entity_id, None)
                
                return True
            except Exception as e:
                self._log(f"[SYNC] {entity_id}: apply failed: {e}")
                return False
        return False
    
    def _log(self, message: str) -> None:
        """Логирование"""
        if self._log_callback:
            self._log_callback(message)
        else:
            print(message)
    
    # ===== Диагностика =====
    
    def get_status(self) -> dict:
        """Получить статус синхронизации всех устройств"""
        result = {}
        for entity_id in self._desired:
            desired = self._desired.get(entity_id)
            actual = self._actual.get(entity_id)
            divergence = self._divergences.get(entity_id)
            
            result[entity_id] = {
                "desired": desired.state if desired else None,
                "actual": actual.state if actual else None,
                "source": desired.source if desired else None,
                "in_sync": desired.state == actual.state if desired and actual else None,
                "manual_locked": self.is_manual_locked(entity_id),
                "divergence_sec": divergence.duration_sec if divergence else 0
            }
        return result
    
    def get_divergences(self) -> list[Divergence]:
        """Получить все активные расхождения"""
        return list(self._divergences.values())

# Глобальный экземпляр
SYNC = SyncEngine()
