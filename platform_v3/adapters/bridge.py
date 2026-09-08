"""
Action Bridge & State Sync - Мосты между FSM и Home Assistant

Этот модуль решает две критические проблемы:
1. ActionBridge: Переход FSM -> Команда в HA (свет физически включается)
2. StateSync: Изменение в HA -> Обновление FSM (рассинхрон состояний)

Usage:
    # При инициализации платформы
    bridge = ActionBridge(event_bus, ha_adapter, logger)
    sync = StateSync(event_bus, fsm_engine, logger)
    
    # Bridge автоматически подпишется на fsm.transition
    # Sync автоматически подпишется на ha.state_changed
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.fsm import FSMEngine
    from adapters.ha_adapter import HomeAssistantAdapter
    from core.logger import Logger


class ActionBridge:
    """
    Мост для выполнения действий при переходах FSM
    
    Подписывается на события fsm.transition и отправляет команды в HA.
    
    Mapping состояний в команды:
    - ON_SCHEDULE, ON_MOTION, PARTY, NIGHTLIGHT, MANUAL -> turn_on
    - OFF -> turn_off
    """
    
    def __init__(self, event_bus: EventBus, adapter: HomeAssistantAdapter, logger: Logger):
        self._event_bus = event_bus
        self._adapter = adapter
        self._logger = logger
        
        # Подписываемся на переходы FSM
        event_bus.subscribe("fsm.transition", self._on_fsm_transition)
        
        self._logger.info("ActionBridge initialized")
    
    def _on_fsm_transition(self, data: dict) -> None:
        """
        Обработчик перехода FSM
        
        Args:
            data: {
                "entity_id": "light.living_room",
                "from_state": "OFF",
                "to_state": "ON_SCHEDULE",
                "trigger": "schedule_on",
                "reason": "Включение по расписанию"
            }
        """
        entity_id = data.get("entity_id")
        to_state = data.get("to_state")
        from_state = data.get("from_state")
        
        if not entity_id or not to_state:
            self._logger.error("Invalid transition data", data=data)
            return
        
        # Определяем команду на основе состояния
        command = self._state_to_command(to_state)
        
        if command is None:
            # Состояние не требует изменения физического устройства
            self._logger.debug(
                f"No physical action for state {to_state}",
                entity_id=entity_id,
                to_state=to_state
            )
            return
        
        # Отправляем команду в HA
        self._send_command(entity_id, command, from_state, to_state)
    
    def _state_to_command(self, state: str) -> str | None:
        """
        Преобразует состояние FSM в команду HA
        
        Returns:
            "turn_on", "turn_off" или None (если действие не требуется)
        """
        # Состояния когда свет должен быть включен
        on_states = {
            "ON_SCHEDULE",
            "ON_MOTION", 
            "PARTY",
            "NIGHTLIGHT",
            "MANUAL"
        }
        
        if state in on_states:
            return "turn_on"
        elif state == "OFF":
            return "turn_off"
        else:
            return None
    
    def _send_command(self, entity_id: str, command: str, from_state: str, to_state: str) -> None:
        """Отправить команду в HA"""
        try:
            # Для async контекста (когда запущено как отдельный сервис)
            if hasattr(self._adapter, 'set_entity_state'):
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    # Создаём задачу чтобы не блокировать event loop
                    task = asyncio.create_task(
                        self._adapter.set_entity_state(entity_id, "on" if command == "turn_on" else "off")
                    )
                    self._logger.info(
                        f"Command sent: {command}",
                        entity_id=entity_id,
                        from_state=from_state,
                        to_state=to_state,
                        async_mode=True
                    )
                except RuntimeError:
                    # Нет running loop (синхронный контекст)
                    self._send_sync(entity_id, command, from_state, to_state)
            else:
                # Mock adapter или другой адаптер без async
                self._send_sync(entity_id, command, from_state, to_state)
                
        except Exception as e:
            self._logger.error(
                f"Failed to send command: {e}",
                entity_id=entity_id,
                command=command,
                error=str(e)
            )
    
    def _send_sync(self, entity_id: str, command: str, from_state: str, to_state: str) -> None:
        """Синхронная отправка команды (для тестов и mock adapter)"""
        if hasattr(self._adapter, 'send_command'):
            # Mock adapter
            self._adapter.send_command(entity_id, command)
        elif hasattr(self._adapter, 'set_state'):
            # Другой тип mock
            new_state = "on" if command == "turn_on" else "off"
            self._adapter.set_state(entity_id, new_state)
        
        self._logger.info(
            f"Command sent (sync): {command}",
            entity_id=entity_id,
            from_state=from_state,
            to_state=to_state,
            async_mode=False
        )


class StateSync:
    """
    Синхронизация физического состояния HA с FSM
    
    Решает проблему рассинхрона (State Drift):
    - Если пользователь нажал физический выключатель
    - Если команда из HA пришла раньше чем обновился FSM
    - При перезапуске платформы
    
    Стратегии синхронизации:
    1. При старте: загрузить все состояния из HA и синхронизировать FSM
    2. При изменении: если физическое состояние != ожидаемого, триггерить manual_change
    """
    
    def __init__(self, event_bus: EventBus, fsm_engine: FSMEngine, logger: Logger):
        self._event_bus = event_bus
        self._fsm_engine = fsm_engine
        self._logger = logger
        
        # Подписываемся на изменения состояний в HA
        event_bus.subscribe("ha.state_changed", self._on_ha_state_change)
        event_bus.subscribe("ha.entity.changed", self._on_ha_entity_changed)
        
        self._logger.info("StateSync initialized")
    
    def _on_ha_state_change(self, data: dict) -> None:
        """
        Обработчик изменения состояния в HA
        
        Args:
            data: {
                "entity_id": "light.living_room",
                "old_state": "off",
                "new_state": "on"
            }
        """
        entity_id = data.get("entity_id")
        new_state = data.get("new_state")
        old_state = data.get("old_state")
        
        if not entity_id or not new_state:
            return
        
        # Проверяем есть ли такой автомат
        fsm_state = self._fsm_engine.get_state(entity_id)
        if not fsm_state:
            # Автомат не зарегистрирован, игнорируем
            return
        
        # Определяем ожидаемое физическое состояние FSM
        expected_physical = self._fsm_state_to_physical(fsm_state.current)
        
        # Конвертируем состояние HA в наш формат
        actual_physical = self._ha_state_to_physical(new_state)
        
        # Если рассинхрон - триггерим manual_change
        if expected_physical != actual_physical:
            self._logger.info(
                f"State drift detected, syncing...",
                entity_id=entity_id,
                fsm_state=fsm_state.current,
                expected_physical=expected_physical,
                actual_physical=actual_physical,
                ha_state=new_state
            )
            
            # Триггерим ручное изменение чтобы FSM обновился
            self._fsm_engine.trigger(entity_id, "manual_change", {
                "physical_state": actual_physical,
                "ha_state": new_state,
                "reason": "State sync"
            })
    
    def _on_ha_entity_changed(self, data: dict) -> None:
        """Альтернативный обработчик от HA Adapter"""
        self._on_ha_state_change(data)
    
    def _fsm_state_to_physical(self, fsm_state: str) -> str:
        """Преобразует состояние FSM в физическое (on/off)"""
        on_states = {"ON_SCHEDULE", "ON_MOTION", "PARTY", "NIGHTLIGHT", "MANUAL"}
        return "on" if fsm_state in on_states else "off"
    
    def _ha_state_to_physical(self, ha_state: str) -> str:
        """Преобразует состояние HA в физическое (on/off)"""
        if ha_state is None:
            return "off"
        ha_state_lower = str(ha_state).lower()
        if ha_state_lower in ("on", "open", "active", "home"):
            return "on"
        return "off"
    
    async def sync_all_at_startup(self, adapter: HomeAssistantAdapter) -> None:
        """
        Синхронизировать все автоматы при старте
        
        Вызывать после подключения к HA но до начала работы
        """
        self._logger.info("Syncing all states at startup...")
        
        try:
            entities = await adapter.get_all_entities()
            
            for entity in entities:
                entity_id = entity.entity_id
                ha_state = entity.state
                
                # Проверяем есть ли такой автомат
                fsm_state = self._fsm_engine.get_state(entity_id)
                if not fsm_state:
                    continue
                
                # Синхронизируем если нужно
                expected = self._fsm_state_to_physical(fsm_state.current)
                actual = self._ha_state_to_physical(ha_state)
                
                if expected != actual:
                    self._logger.info(
                        f"Startup sync: {entity_id}",
                        fsm_state=fsm_state.current,
                        ha_state=ha_state
                    )
                    
                    # Триггерим sync чтобы привести FSM в соответствие с HA
                    self._fsm_engine.trigger(entity_id, "sync_state", {
                        "physical_state": actual,
                        "ha_state": ha_state,
                        "reason": "Startup sync"
                    })
            
            self._logger.info(f"Startup sync complete. Processed {len(entities)} entities")
            
        except Exception as e:
            self._logger.error(f"Startup sync failed: {e}", error=str(e))


def setup_integration_bridge(
    event_bus: EventBus,
    fsm_engine: FSMEngine,
    adapter: HomeAssistantAdapter,
    logger: Logger
) -> tuple[ActionBridge, StateSync]:
    """
    Настроить мосты между FSM и HA
    
    Convenience функция для инициализации всех桥 components
    
    Returns:
        (ActionBridge, StateSync) кортеж созданных компонентов
    """
    bridge = ActionBridge(event_bus, adapter, logger)
    sync = StateSync(event_bus, fsm_engine, logger)
    
    logger.info("Integration bridges configured")
    
    return bridge, sync
