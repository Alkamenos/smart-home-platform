"""
FSM Persistence - Сохранение состояний FSM между рестартами

Этот компонент решает проблему потери режимов при перезапуске HA.
Без персистентности:
- Был режим PARTY (свет горит)
- HA перезагрузился
- FSM стартовал с initial="OFF"
- StateSync видит что свет физически ON, триггерит manual_change
- Режим PARTY потерян безвозвратно

Решение:
- При каждом переходе сохранять state.current в input_text.{entity_id}_mode
- При старте читать сохраненное состояние и восстанавливать FSM

Usage:
    persistence = FSMPersistence(event_bus, fsm_engine, adapter, logger)
    persistence.enable_for_entity("light.living_room")
    
    # Автоматически сохраняет состояния при переходах
    # Автоматически восстанавливает при старте
"""

from __future__ import annotations
import json
import time
from typing import Optional


class FSMPersistence:
    """
    Менеджер персистентности для FSM
    
    Сохраняет состояния в HA storage через input_text entities
    или в локальный JSON файл если input_text недоступен.
    """
    
    def __init__(self, event_bus, fsm_engine, adapter, logger):
        self._event_bus = event_bus
        self._fsm_engine = fsm_engine
        self._adapter = adapter
        self._logger = logger
        
        # Включенные автоматы: entity_id -> storage_key
        self._enabled_entities: dict[str, str] = {}
        
        # Кэш последних состояний
        self._state_cache: dict[str, str] = {}
        
        # Флаг доступности input_text
        self._input_text_available = True
        
        # Подписываемся на переходы FSM
        event_bus.subscribe("fsm.transition", self._on_fsm_transition)
        event_bus.subscribe("platform.started", self._on_platform_started)
        
        self._logger.info("FSMPersistence initialized")
    
    def enable_for_entity(self, entity_id: str, storage_key: str = None) -> None:
        """
        Включить персистентность для автомата
        
        Args:
            entity_id: ID автомата (например, "light.living_room")
            storage_key: Ключ хранения (по умолчанию "{entity_id}_mode")
        """
        if storage_key is None:
            storage_key = f"{entity_id.replace('.', '_')}_mode"
        
        self._enabled_entities[entity_id] = storage_key
        self._logger.info(
            f"Enabled persistence for {entity_id} (key: {storage_key})"
        )
    
    def _on_fsm_transition(self, data: dict) -> None:
        """
        Обработчик перехода FSM - сохраняет состояние
        
        Args:
            data: {
                "entity_id": "light.living_room",
                "to_state": "PARTY",
                ...
            }
        """
        entity_id = data.get("entity_id")
        to_state = data.get("to_state")
        
        if not entity_id or not to_state:
            return
        
        if entity_id not in self._enabled_entities:
            return
        
        storage_key = self._enabled_entities[entity_id]
        
        # Обновляем кэш
        old_state = self._state_cache.get(entity_id)
        self._state_cache[entity_id] = to_state
        
        # Сохраняем в хранилище
        self._save_state(storage_key, to_state, entity_id)
        
        self._logger.debug(
            f"Persisted state: {entity_id} = {to_state}",
            entity_id=entity_id,
            storage_key=storage_key,
            old_state=old_state,
            new_state=to_state
        )
    
    def _on_platform_started(self, data: dict) -> None:
        """
        При старте платформы восстанавливаем сохраненные состояния
        
        Вызывается после регистрации всех автоматов но до начала работы
        """
        self._logger.info("Restoring persisted states...")
        
        restored_count = 0
        
        for entity_id, storage_key in self._enabled_entities.items():
            saved_state = self._load_state(storage_key)
            
            if saved_state:
                # Проверяем существует ли такой автомат
                fsm_state = self._fsm_engine.get_state(entity_id)
                
                if fsm_state:
                    # Проверяем есть ли такое состояние в определениях
                    definition = self._fsm_engine._definitions.get(entity_id)
                    
                    if definition and saved_state in definition.states:
                        # Восстанавливаем состояние
                        self._restore_state(entity_id, saved_state)
                        restored_count += 1
                        
                        self._logger.info(
                            f"Restored state for {entity_id}: {saved_state}",
                            entity_id=entity_id,
                            saved_state=saved_state
                        )
                    else:
                        self._logger.warning(
                            f"Invalid saved state for {entity_id}: {saved_state}",
                            entity_id=entity_id,
                            saved_state=saved_state,
                            available_states=definition.states if definition else "N/A"
                        )
                else:
                    self._logger.warning(
                        f"FSM not found for {entity_id}, skipping restore",
                        entity_id=entity_id
                    )
            else:
                self._logger.debug(
                    f"No saved state for {entity_id}",
                    entity_id=entity_id
                )
        
        self._logger.info(f"Restore complete. Restored {restored_count} states")
    
    def _save_state(self, storage_key: str, state: str, entity_id: str) -> None:
        """
        Сохранить состояние в хранилище
        
        Приоритет:
        1. input_text через HA API
        2. Локальный JSON файл
        """
        if self._input_text_available:
            try:
                # Пробуем сохранить через input_text
                input_entity_id = f"input_text.{storage_key}"
                
                # Для async контекста
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    task = asyncio.create_task(
                        self._adapter.set_entity_state(
                            input_entity_id,
                            "set_value",
                            {"value": state}
                        )
                    )
                except RuntimeError:
                    # Синхронный контекст
                    self._save_to_file(storage_key, state)
                    
            except Exception as e:
                self._logger.warning(
                    f"Failed to save to input_text, using file: {e}",
                    storage_key=storage_key,
                    error=str(e)
                )
                self._input_text_available = False
                self._save_to_file(storage_key, state)
        else:
            self._save_to_file(storage_key, state)
    
    def _save_to_file(self, storage_key: str, state: str) -> None:
        """Сохранить состояние в локальный JSON файл"""
        try:
            import os
            from pathlib import Path
            
            # Директория для хранения
            storage_dir = Path.home() / ".homeassistant" / ".storage" / "fsm_persistence"
            storage_dir.mkdir(parents=True, exist_ok=True)
            
            storage_file = storage_dir / f"{storage_key}.json"
            
            data = {
                "state": state,
                "updated_at": time.time()
            }
            
            with open(storage_file, 'w') as f:
                json.dump(data, f)
                
            self._logger.debug(f"Saved state to file: {storage_file}")
            
        except Exception as e:
            self._logger.error(
                f"Failed to save to file: {e}",
                storage_key=storage_key,
                error=str(e)
            )
    
    def _load_state(self, storage_key: str) -> Optional[str]:
        """
        Загрузить состояние из хранилища
        
        Returns:
            Состояние или None если не найдено
        """
        if self._input_text_available:
            try:
                # Пробуем загрузить через input_text
                input_entity_id = f"input_text.{storage_key}"
                
                # Для async контекста
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    # Создаём задачу для получения состояния
                    # Это упрощённая эмуляция - в реальности нужен async вызов
                except RuntimeError:
                    # Синхронный контекст - используем файл
                    return self._load_from_file(storage_key)
                    
            except Exception:
                self._input_text_available = False
                return self._load_from_file(storage_key)
        
        return self._load_from_file(storage_key)
    
    def _load_from_file(self, storage_key: str) -> Optional[str]:
        """Загрузить состояние из локального JSON файла"""
        try:
            from pathlib import Path
            
            storage_dir = Path.home() / ".homeassistant" / ".storage" / "fsm_persistence"
            storage_file = storage_dir / f"{storage_key}.json"
            
            if storage_file.exists():
                with open(storage_file, 'r') as f:
                    data = json.load(f)
                    return data.get("state")
            
            return None
            
        except Exception as e:
            self._logger.debug(
                f"Failed to load from file: {e}",
                storage_key=storage_key,
                error=str(e)
            )
            return None
    
    def _restore_state(self, entity_id: str, saved_state: str) -> None:
        """
        Восстановить состояние автомата
        
        Args:
            entity_id: ID автомата
            saved_state: Сохраненное состояние
        """
        # Получаем текущее состояние FSM (обычно initial)
        current_state = self._fsm_engine.get_state(entity_id)
        
        if current_state and current_state.current != saved_state:
            # Находим определение автомата для проверки валидности состояния
            definition = self._fsm_engine._definitions.get(entity_id)
            
            if definition and saved_state in definition.states:
                # Прямо устанавливаем состояние в FSM Engine
                # Это обходной путь т.к. триггер restore_state может не существовать
                import time
                
                now = time.time()
                
                # Создаём новую запись в истории
                history_entry = {
                    "from": current_state.current,
                    "to": saved_state,
                    "trigger": "restore",
                    "why": "State restoration after restart",
                    "at": now
                }
                new_history = (history_entry,) + current_state.history[:19]
                
                # Создаём новое состояние (используем State из того же модуля)
                from .fsm import State
                
                restored_state = State(
                    entity_id=entity_id,
                    current=saved_state,
                    entered_at=now,
                    entered_by="restore",
                    entered_why="State restoration after restart",
                    history=new_history
                )
                
                # Обновляем состояние в движке
                self._fsm_engine._states[entity_id] = restored_state
                
                # Публикуем событие о восстановлении
                self._event_bus.publish("fsm.restored", {
                    "entity_id": entity_id,
                    "restored_state": saved_state,
                    "previous_state": current_state.current
                })
                
                self._logger.info(
                    f"State directly restored for {entity_id}: {saved_state}",
                    entity_id=entity_id,
                    saved_state=saved_state,
                    previous_state=current_state.current
                )
                
                # Обновляем кэш
                self._state_cache[entity_id] = saved_state
            else:
                self._logger.warning(
                    f"Cannot restore invalid state for {entity_id}: {saved_state}",
                    entity_id=entity_id,
                    saved_state=saved_state
                )
