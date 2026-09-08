"""
Watchdog Service - периодическое логирование состояний FSM

Используется для мониторинга и отладки платформы в production.
Запускает фоновую задачу, которая раз в 60 секунд логирует JSON-снимок
всех состояний автоматов.

Usage:
    watchdog = WatchdogService(fsm_engine, registry, ha_adapter)
    await watchdog.start()
    
    # Или ручной вызов
    await watchdog.log_snapshot_now()
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from core.logger import get_logger

if TYPE_CHECKING:
    from core.fsm import FSMEngine
    from core.registry import Registry
    from adapters.ha_adapter import HomeAssistantAdapter

logger = get_logger(__name__)


class WatchdogService:
    """
    Сервис периодического мониторинга состояний FSM.
    
    Функции:
    - Автоматическое логирование состояний раз в N секунд
    - Ручной вызов логирования по требованию
    - Форматирование вывода в JSON для удобного парсинга
    """
    
    def __init__(
        self,
        fsm_engine: 'FSMEngine',
        registry: 'Registry',
        ha_adapter: 'HomeAssistantAdapter',
        interval_sec: int = 60
    ):
        self.fsm_engine = fsm_engine
        self.registry = registry
        self.ha_adapter = ha_adapter
        self.interval_sec = interval_sec
        
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Запустить фоновую задачу периодического логирования"""
        if self._running:
            logger.warning("Watchdog already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._watchdog_loop())
        logger.info(f"Watchdog started (interval={self.interval_sec}s)")
    
    async def stop(self):
        """Остановить фоновую задачу"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Watchdog stopped")
    
    async def _watchdog_loop(self):
        """Фоновый цикл логирования"""
        while self._running:
            try:
                await self.log_snapshot_now()
                await asyncio.sleep(self.interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                await asyncio.sleep(self.interval_sec)
    
    def log_snapshot_now(self):
        """
        Логировать текущий снимок состояний всех FSM.
        
        Формат вывода (JSON):
        {
            "timestamp": "2024-01-15T10:30:00",
            "fsm_count": 3,
            "states": {
                "light.living_room": {"state": "ON", "context": {...}},
                "climate.bedroom": {"state": "AUTO", "context": {...}}
            }
        }
        """
        try:
            states = self.fsm_engine.get_all_states()
            
            snapshot = {
                "timestamp": datetime.now().isoformat(),
                "fsm_count": len(states),
                "states": {}
            }
            
            for entity_id, state_obj in states.items():
                # Сериализуем состояние
                # State - это dataclass, нужно извлечь поле current
                if hasattr(state_obj, 'current'):
                    state_value = state_obj.current
                elif hasattr(state_obj, 'state'):
                    state_value = state_obj.state
                else:
                    state_value = str(state_obj)
                
                state_data = {
                    "state": state_value,
                }
                
                # Добавляем context если есть
                if hasattr(state_obj, 'context') and state_obj.context:
                    state_data["context"] = state_obj.context
                
                snapshot["states"][entity_id] = state_data
            
            # Логируем в JSON формате
            snapshot_json = json.dumps(snapshot, ensure_ascii=False)
            logger.info(f"[WATCHDOG] {snapshot_json}")
            
            # Также можно отправить в HA как событие (опционально)
            # self.event_bus.publish('platform.watchdog.snapshot', snapshot)
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Failed to create watchdog snapshot: {e}")
            return None


# Глобальный экземпляр для использования в PyScript
_watchdog_instance: Optional[WatchdogService] = None


def create_watchdog(
    fsm_engine: 'FSMEngine',
    registry: 'Registry',
    ha_adapter: 'HomeAssistantAdapter',
    interval_sec: int = 60
) -> WatchdogService:
    """Создать и вернуть экземпляр WatchdogService"""
    global _watchdog_instance
    _watchdog_instance = WatchdogService(
        fsm_engine=fsm_engine,
        registry=registry,
        ha_adapter=ha_adapter,
        interval_sec=interval_sec
    )
    return _watchdog_instance


def get_watchdog() -> Optional[WatchdogService]:
    """Получить глобальный экземпляр WatchdogService"""
    return _watchdog_instance
