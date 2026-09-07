#!/usr/bin/env python3
"""
Override Manager V2 — единый механизм ручного вмешательства.

Решает проблему разрозненной логики блокировок в разных фичах.

Принципы:
- Единый менеджер для всех фич
- Блокировка по сущности с истечением по времени
- Причина блокировки, источник
- Возможность снятия блокировки
- История блокировок
"""
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class Override:
    """Блокировка устройства"""
    entity_id: str
    source: str  # "manual", "dashboard", "button", "voice"
    reason: str
    created_at: float
    expires_at: float
    
    @property
    def remaining_sec(self) -> float:
        return max(0, self.expires_at - time.monotonic())
    
    @property
    def remaining_min(self) -> float:
        return self.remaining_sec / 60

class OverrideManager:
    """Менеджер блокировок"""
    
    def __init__(self, default_timeout_min: int = 60):
        self._overrides: dict[str, Override] = {}
        self._history: list[Override] = []
        self._default_timeout = default_timeout_min * 60
        self._log_callback = None
    
    def set_log_callback(self, callback):
        """Установить функцию логирования"""
        self._log_callback = callback
    
    def set_override(self, entity_id: str, source: str = "manual",
                     reason: str = "", timeout_min: int = None) -> None:
        """Установить блокировку"""
        # Правильно обрабатываем timeout_min=0 (не путаем с None)
        if timeout_min is not None:
            timeout = timeout_min * 60
        else:
            timeout = self._default_timeout
        
        override = Override(
            entity_id=entity_id,
            source=source,
            reason=reason,
            created_at=time.monotonic(),
            expires_at=time.monotonic() + timeout
        )
        
        self._overrides[entity_id] = override
        self._history.append(override)
        
        # Ограничиваем историю
        if len(self._history) > 100:
            self._history = self._history[-100:]
        
        self._log(f"[OVERRIDE] {entity_id}: blocked {timeout_min or self._default_timeout/60:.0f} min ({source}: {reason})")
    
    def is_overridden(self, entity_id: str) -> bool:
        """Проверить, заблокировано ли устройство"""
        override = self._overrides.get(entity_id)
        if not override:
            return False
        
        if time.monotonic() > override.expires_at:
            del self._overrides[entity_id]
            return False
        
        return True
    
    def get_override(self, entity_id: str) -> Optional[Override]:
        """Получить блокировку"""
        if self.is_overridden(entity_id):
            return self._overrides.get(entity_id)
        return None
    
    def release(self, entity_id: str) -> None:
        """Снять блокировку"""
        if entity_id in self._overrides:
            del self._overrides[entity_id]
            self._log(f"[OVERRIDE] {entity_id}: released")
    
    def release_all(self) -> None:
        """Снять все блокировки"""
        count = len(self._overrides)
        self._overrides.clear()
        self._log(f"[OVERRIDE] Released {count} overrides")
    
    def get_all_active(self) -> list[Override]:
        """Получить все активные блокировки"""
        now = time.monotonic()
        active = []
        expired = []
        
        for entity_id, override in self._overrides.items():
            if now <= override.expires_at:
                active.append(override)
            else:
                expired.append(entity_id)
        
        # Удаляем истёкшие
        for entity_id in expired:
            del self._overrides[entity_id]
        
        return active
    
    def get_history(self, limit: int = 20) -> list[Override]:
        """Получить историю блокировок"""
        return self._history[-limit:]
    
    def _log(self, message: str) -> None:
        """Логирование"""
        if self._log_callback:
            self._log_callback(message)
        else:
            print(message)

# Глобальный экземпляр
OVERRIDE = OverrideManager()
