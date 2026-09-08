"""
Trigger Mapper - Связывает сенсоры HA с триггерами FSM

Принцип работы:
- Декларативный маппинг в FSMDefinition: triggers_mapping = {"motion_detected": "binary_sensor.living_room_motion"}
- При изменении сенсора вызывается fsm.trigger(entity_id, trigger_name, context)
- Позволяет избежать хардкода @state_trigger в loader.py
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from core.fsm import FSMEngine, FSMDefinition


class BaseTriggerMapper(ABC):
    """Абстракция маппера триггеров"""
    
    @abstractmethod
    def register_definition(self, definition: FSMDefinition) -> None:
        """Регистрирует все триггеры из triggers_mapping для данного автомата"""
        pass
    
    @abstractmethod
    def unregister_definition(self, entity_id: str) -> None:
        """Отписывает все триггеры для данного автомата"""
        pass


class MockTriggerMapper(BaseTriggerMapper):
    """
    Mock-реализация для тестов.
    Позволяет вручную вызывать триггеры по entity_id сенсора.
    
    Usage в тестах:
        mapper = MockTriggerMapper(fsm_engine)
        mapper.register_definition(definition)
        mapper.trigger("binary_sensor.living_room_motion", "on")  # Вызовет fsm.trigger(...)
    """
    
    def __init__(self, fsm_engine: FSMEngine):
        self._fsm_engine = fsm_engine
        self._registrations: Dict[str, Dict[str, str]] = {}  # {ha_entity_id: {trigger_name: fsm_entity_id}}
    
    def register_definition(self, definition: FSMDefinition) -> None:
        """Регистрирует маппинг триггеров"""
        for trigger_name, ha_entity_id in definition.triggers_mapping.items():
            if ha_entity_id not in self._registrations:
                self._registrations[ha_entity_id] = {}
            self._registrations[ha_entity_id][trigger_name] = definition.entity_id
    
    def unregister_definition(self, entity_id: str) -> None:
        """Отписывает триггеры для данного автомата"""
        to_remove = []
        for ha_entity_id, mappings in self._registrations.items():
            for trigger_name, fsm_entity_id in list(mappings.items()):
                if fsm_entity_id == entity_id:
                    del mappings[trigger_name]
            if not mappings:
                to_remove.append(ha_entity_id)
        for ha_entity_id in to_remove:
            del self._registrations[ha_entity_id]
    
    def trigger(self, ha_entity_id: str, new_value: Any, old_value: Any = None) -> None:
        """
        Вызывает соответствующий триггер в FSM.
        
        Args:
            ha_entity_id: ID сенсора в HA (например, "binary_sensor.living_room_motion")
            new_value: Новое значение сенсора
            old_value: Старое значение сенсора (опционально)
        """
        if ha_entity_id not in self._registrations:
            return
        
        context = {
            "entity_id": ha_entity_id,
            "new_value": new_value,
            "old_value": old_value
        }
        
        # Для binary_sensor: True -> motion_detected, False -> motion_cleared
        # Определяем какой триггер вызвать на основе имени и значения
        for trigger_name, fsm_entity_id in self._registrations[ha_entity_id].items():
            trigger_lower = trigger_name.lower()
            
            # Пропускаем триггеры которые не соответствуют текущему значению
            if ("cleared" in trigger_lower or "off" in trigger_lower) and new_value is True:
                continue  # Пропускаем cleared/off при True
            if ("detected" in trigger_lower or "on" in trigger_lower) and new_value is False:
                continue  # Пропускаем detected/on при False
            
            # Вызываем триггер
            self._fsm_engine.trigger(fsm_entity_id, trigger_name, context)


class HaTriggerMapper(BaseTriggerMapper):
    """
    HA-реализация для production (PyScript).
    Использует @state_trigger динамически через pyscript API.
    
    Примечание: В PyScript @state_trigger должен быть на уровне модуля.
    Эта реализация создает обертки для регистрации триггеров.
    """
    
    def __init__(self, fsm_engine: FSMEngine, logger):
        self._fsm_engine = fsm_engine
        self._logger = logger
        self._registrations: Dict[str, Dict[str, str]] = {}  # {ha_entity_id: {trigger_name: fsm_entity_id}}
        self._active_triggers: set = set()  # set of ha_entity_id уже зарегистрированных
    
    def register_definition(self, definition: FSMDefinition) -> None:
        """Регистрирует маппинг триггеров"""
        for trigger_name, ha_entity_id in definition.triggers_mapping.items():
            if ha_entity_id not in self._registrations:
                self._registrations[ha_entity_id] = {}
                
                # Регистрируем глобальный обработчик для этого сенсора
                # В PyScript это должно быть выполнено на уровне модуля
                self._register_sensor_listener(ha_entity_id)
            
            self._registrations[ha_entity_id][trigger_name] = definition.entity_id
    
    def _register_sensor_listener(self, ha_entity_id: str) -> None:
        """
        Регистрирует слушатель изменений для сенсора.
        В PyScript использует @state_trigger, в тестах - ничего не делает.
        """
        if ha_entity_id in self._active_triggers:
            return
        
        self._active_triggers.add(ha_entity_id)
        
        # В реальном PyScript здесь был бы @state_trigger декоратор
        # Для совместимости оставляем заглушку - реальная регистрация происходит в loader.py
        self._logger.debug(f"Registered sensor listener for {ha_entity_id}")
    
    def handle_sensor_change(self, ha_entity_id: str, new_value: Any, old_value: Any = None) -> None:
        """
        Обработчик изменения сенсора (вызывается из @state_trigger в loader.py).
        
        Args:
            ha_entity_id: ID сенсора в HA
            new_value: Новое значение
            old_value: Старое значение
        """
        if ha_entity_id not in self._registrations:
            return
        
        context = {
            "entity_id": ha_entity_id,
            "new_value": new_value,
            "old_value": old_value
        }
        
        for trigger_name, fsm_entity_id in self._registrations[ha_entity_id].items():
            self._logger.debug(f"Sensor {ha_entity_id} changed -> triggering {trigger_name} on {fsm_entity_id}")
            self._fsm_engine.trigger(fsm_entity_id, trigger_name, context)
    
    def unregister_definition(self, entity_id: str) -> None:
        """Отписывает триггеры для данного автомата"""
        to_remove = []
        for ha_entity_id, mappings in self._registrations.items():
            for trigger_name, fsm_entity_id in list(mappings.items()):
                if fsm_entity_id == entity_id:
                    del mappings[trigger_name]
            if not mappings:
                to_remove.append(ha_entity_id)
        for ha_entity_id in to_remove:
            del self._registrations[ha_entity_id]
            # В PyScript нельзя динамически удалить @state_trigger, поэтому оставляем активным
