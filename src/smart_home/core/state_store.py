"""
State Store - Абстрактное хранилище состояний FSM

Интерфейс для сохранения/загрузки состояний автоматов.
Поддерживает несколько реализаций:
- MemoryStateStore (для тестов)
- FileStateStore (для локального хранения в JSON)
- InputTextStateStore (для HA input_text helpers)
- DebouncedStateStore (обёртка для дебаунса записей)

Принципы:
1. Атомарность записи (нет частичных данных при сбое)
2. Дебаунс (не пишем на каждый переход - бережём SD карту)
3. Версионирование формата (миграция при изменении структуры)
4. Все методы async (совместимость с PyScript)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pathlib import Path
import json
import time
import os
import tempfile
import asyncio


class StateStore(ABC):
    """
    Абстрактное хранилище состояний автоматов.
    
    Реализации:
    - MemoryStateStore (для тестов)
    - FileStateStore (для локального хранения)
    - InputTextStateStore (для HA input_text)
    - DebouncedStateStore (обёртка для дебаунса)
    """
    
    @abstractmethod
    async def save(self, entity_id: str, state_data: dict) -> bool:
        """
        Сохранить состояние автомата.
        
        Args:
            entity_id: ID автомата (например, "light.kitchen")
            state_data: Данные состояния:
                {
                    "current": "ON_MOTION",
                    "entered_at": 1694184000.0,
                    "entered_by": "motion_detected",
                    "entered_why": "Обнаружено движение",
                    "history": [...],
                    "last_manual_control_at": 1694184000.0  # опционально
                }
        
        Returns:
            True если сохранение успешно
        """
        pass
    
    @abstractmethod
    async def load(self, entity_id: str) -> Optional[dict]:
        """
        Загрузить состояние автомата.
        
        Args:
            entity_id: ID автомата
        
        Returns:
            Данные состояния или None если не найдено
        """
        pass
    
    @abstractmethod
    async def load_all(self) -> dict[str, dict]:
        """
        Загрузить все сохраненные состояния.
        
        Returns:
            dict {entity_id: state_data}
        """
        pass
    
    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """
        Удалить сохраненное состояние.
        
        Args:
            entity_id: ID автомата
        
        Returns:
            True если удаление успешно (или состояния не существовало)
        """
        pass
    
    @abstractmethod
    async def clear(self) -> None:
        """
        Очистить всё хранилище.
        """
        pass


class MemoryStateStore(StateStore):
    """
    Хранение в памяти (для тестов и отладки).
    
    Не сохраняет данные между перезапусками.
    Потокобезопасная реализация для concurrent доступа.
    """
    
    def __init__(self, logger=None):
        self._store: dict[str, dict] = {}
        self._logger = logger
        self._lock = asyncio.Lock()
    
    async def save(self, entity_id: str, state_data: dict) -> bool:
        async with self._lock:
            self._store[entity_id] = dict(state_data)
            if self._logger:
                self._logger.debug(f"MemoryStore saved {entity_id}")
        return True
    
    async def load(self, entity_id: str) -> Optional[dict]:
        async with self._lock:
            data = self._store.get(entity_id)
            if data:
                return dict(data)  # Возвращаем копию
            return None
    
    async def load_all(self) -> dict[str, dict]:
        async with self._lock:
            return {k: dict(v) for k, v in self._store.items()}
    
    async def delete(self, entity_id: str) -> bool:
        async with self._lock:
            if entity_id in self._store:
                del self._store[entity_id]
                if self._logger:
                    self._logger.debug(f"MemoryStore deleted {entity_id}")
            return True
    
    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            if self._logger:
                self._logger.info("MemoryStore cleared")


class FileStateStore(StateStore):
    """
    Хранение в JSON файле.
    
    Особенности:
    - Атомарная запись (сначала во временный файл, потом rename)
    - Дебаунс записи (не пишем каждый переход)
    - Версионирование формата
    - Автоматическое создание директории
    """
    
    CURRENT_VERSION = 1
    
    def __init__(self, path: str, debounce_sec: float = 5.0, logger=None):
        self._path = Path(path)
        self._debounce_sec = debounce_sec
        self._logger = logger
        self._version = self.CURRENT_VERSION
        
        # Кэш данных в памяти
        self._cache: dict[str, dict] = {}
        self._cache_loaded = False
        
        # Debounce tracking
        self._last_write_time = 0.0
        self._pending_writes: set[str] = set()
        self._write_lock = asyncio.Lock()
    
    async def _ensure_cache_loaded(self) -> None:
        """Загрузить кэш из файла если ещё не загружен"""
        if self._cache_loaded:
            return
        
        try:
            if self._path.exists() and self._path.stat().st_size > 0:
                with open(self._path, 'r') as f:
                    data = json.load(f)
                    
                    # Проверяем версию
                    version = data.get('version', 0)
                    if version != self._version:
                        if self._logger:
                            self._logger.warning(
                                f"State file version mismatch: {version} != {self._version}, attempting migration"
                            )
                        data = await self._migrate(data, version)
                    
                    self._cache = data.get('states', {})
                    if self._logger:
                        self._logger.info(
                            f"Loaded {len(self._cache)} states from {self._path}"
                        )
            else:
                if self._logger:
                    self._logger.debug(f"State file does not exist or is empty: {self._path}")
        except json.JSONDecodeError as e:
            if self._logger:
                self._logger.error(f"Corrupted state file: {e}")
            self._cache = {}
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to load state file: {e}")
            self._cache = {}
        
        self._cache_loaded = True
    
    async def _migrate(self, data: dict, from_version: int) -> dict:
        """Миграция данных между версиями"""
        if from_version == 0:
            # Версия 0 -> 1: простая миграция
            data['version'] = 1
            data['updated_at'] = time.time()
            if 'states' not in data:
                data['states'] = {}
        
        # Будущие миграции можно добавить здесь
        # if from_version == 1: ...
        
        return data
    
    async def _save_to_file(self) -> None:
        """Атомарная запись в файл"""
        try:
            # Создаём директорию если нужно
            self._path.parent.mkdir(parents=True, exist_ok=True)
            
            # Готовим данные
            data = {
                'version': self._version,
                'updated_at': time.time(),
                'states': dict(self._cache)
            }
            
            # Атомарная запись: сначала во временный файл
            temp_path = self._path.with_suffix('.tmp')
            
            # Пишем во временный файл
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Атомарный rename
            os.rename(temp_path, self._path)
            
            self._last_write_time = time.time()
            
            if self._logger:
                self._logger.debug(
                    f"Saved {len(self._cache)} states to {self._path}"
                )
                
        except Exception as e:
            self._logger.error(f"Failed to save state file: {e}")
            raise
    
    async def flush(self) -> None:
        """
        Принудительная запись всех ожидающих изменений.
        Вызывать перед завершением работы.
        """
        async with self._write_lock:
            if self._pending_writes or not self._cache_loaded:
                await self._save_to_file()
                self._pending_writes.clear()
        
        if self._logger:
            self._logger.debug("FileStore flushed")
    
    async def save(self, entity_id: str, state_data: dict) -> bool:
        await self._ensure_cache_loaded()
        
        async with self._write_lock:
            self._cache[entity_id] = dict(state_data)
            self._pending_writes.add(entity_id)
        
        if self._logger:
            self._logger.debug(f"FileStore pending save for {entity_id}")
        
        return True
    
    async def load(self, entity_id: str) -> Optional[dict]:
        await self._ensure_cache_loaded()
        
        async with self._write_lock:
            data = self._cache.get(entity_id)
            if data:
                return dict(data)
            return None
    
    async def load_all(self) -> dict[str, dict]:
        await self._ensure_cache_loaded()
        
        async with self._write_lock:
            return {k: dict(v) for k, v in self._cache.items()}
    
    async def delete(self, entity_id: str) -> bool:
        await self._ensure_cache_loaded()
        
        async with self._write_lock:
            if entity_id in self._cache:
                del self._cache[entity_id]
                self._pending_writes.add(entity_id)
            
            return True
    
    async def clear(self) -> None:
        async with self._write_lock:
            self._cache.clear()
            self._pending_writes.clear()
            await self._save_to_file()
        
        if self._logger:
            self._logger.info("FileStore cleared")


class InputTextStateStore(StateStore):
    """
    Хранение в input_text helpers Home Assistant.
    
    Каждый автомат получает свой input_text:
    input_text.platform_v3_{entity_id_safe}
    
    Формат хранения (компактный, < 255 символов):
    light.kitchen|ON_MOTION|1694184000|motion|manual
    
    Поля:
    - entity_id
    - current state
    - entered_at (timestamp)
    - entered_by
    - last_controlled_by (manual/auto)
    
    Ограничения:
    - input_text ограничен 255 символами
    - История переходов не сохраняется (только критичное состояние)
    """
    
    PREFIX = "platform_v3"
    SEPARATOR = "|"
    MAX_LENGTH = 255
    
    def __init__(self, hass=None, logger=None):
        self._hass = hass
        self._logger = logger
        self._state_helper = None  # PyScript state helper
    
    def _entity_to_helper(self, entity_id: str) -> str:
        """Конвертирует entity_id в имя input_text helper"""
        safe_id = entity_id.replace('.', '_').replace('-', '_')
        return f"input_text.{self.PREFIX}_{safe_id}"
    
    def _helper_to_entity(self, helper_name: str) -> str:
        """Конвертирует имя helper обратно в entity_id"""
        prefix = f"input_text.{self.PREFIX}_"
        if helper_name.startswith(prefix):
            safe_id = helper_name[len(prefix):]
            return safe_id.replace('_', '.', 1)  # Заменяем только первую точку
        return helper_name
    
    def _serialize(self, entity_id: str, state_data: dict) -> str:
        """Сериализует данные в компактную строку"""
        current = state_data.get('current', '')
        entered_at = str(int(state_data.get('entered_at', 0)))
        entered_by = state_data.get('entered_by', '')
        last_controlled = state_data.get('last_controlled_by', 'auto')
        
        # Формат: entity_id|state|timestamp|entered_by|last_controlled
        parts = [entity_id, current, entered_at, entered_by, last_controlled]
        result = self.SEPARATOR.join(parts)
        
        if len(result) > self.MAX_LENGTH:
            self._logger.warning(
                f"Serialized state exceeds 255 chars: {len(result)}",
                entity_id=entity_id
            )
        
        return result
    
    def _deserialize(self, data: str) -> Optional[dict]:
        """Десериализует строку обратно в dict"""
        if not data:
            return None
        
        try:
            parts = data.split(self.SEPARATOR)
            if len(parts) < 4:
                self._logger.warning(f"Invalid serialized data: {data}")
                return None
            
            entity_id = parts[0]
            current = parts[1]
            entered_at = float(parts[2]) if parts[2] else 0.0
            entered_by = parts[3]
            last_controlled = parts[4] if len(parts) > 4 else 'auto'
            
            return {
                'current': current,
                'entered_at': entered_at,
                'entered_by': entered_by,
                'last_controlled_by': last_controlled
            }
        except Exception as e:
            self._logger.error(f"Failed to deserialize: {e}, data: {data}")
            return None
    
    async def save(self, entity_id: str, state_data: dict) -> bool:
        """Сохранить состояние в input_text"""
        helper_name = self._entity_to_helper(entity_id)
        serialized = self._serialize(entity_id, state_data)
        
        try:
            # PyScript state.set() API
            if hasattr(self, 'state') and hasattr(self.state, 'set'):
                self.state.set(helper_name, serialized)
                if self._logger:
                    self._logger.debug(f"InputTextStore saved {entity_id} -> {helper_name}")
                return True
            elif self._hass:
                # Home Assistant service call
                await self._hass.services.async_call(
                    'input_text',
                    'set_value',
                    {
                        'entity_id': helper_name,
                        'value': serialized
                    }
                )
                if self._logger:
                    self._logger.debug(f"InputTextStore saved {entity_id} -> {helper_name}")
                return True
            else:
                if self._logger:
                    self._logger.warning(f"No HA instance available, cannot save {entity_id}")
                return False
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to save to input_text: {e}", entity_id=entity_id)
            return False
    
    async def load(self, entity_id: str) -> Optional[dict]:
        """Загрузить состояние из input_text"""
        helper_name = self._entity_to_helper(entity_id)
        
        try:
            # PyScript state.get() API
            if hasattr(self, 'state') and hasattr(self.state, 'get'):
                value = self.state.get(helper_name)
                if value:
                    data = self._deserialize(value)
                    if data:
                        if self._logger:
                            self._logger.debug(f"InputTextStore loaded {entity_id}")
                        return data
            elif self._hass:
                # Home Assistant state
                state = self._hass.states.get(helper_name)
                if state and state.state:
                    data = self._deserialize(state.state)
                    if data:
                        if self._logger:
                            self._logger.debug(f"InputTextStore loaded {entity_id}")
                        return data
            
            if self._logger:
                self._logger.debug(f"No saved state for {entity_id}")
            return None
            
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to load from input_text: {e}", entity_id=entity_id)
            return None
    
    async def load_all(self) -> dict[str, dict]:
        """Загрузить все состояния (сканируя все input_text с префиксом)"""
        result = {}
        
        try:
            if hasattr(self, 'state') and hasattr(self.state, 'get'):
                # PyScript - перебираем возможные entity_id
                # В реальности нужно сканировать через service call
                pass
            elif self._hass:
                # Home Assistant - получаем все input_text с нашим префиксом
                pattern = f"{self.PREFIX}_*"
                # Это требует дополнительного API для сканирования
                pass
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to load all states: {e}")
        
        return result
    
    async def delete(self, entity_id: str) -> bool:
        """Удалить состояние (очистить input_text)"""
        helper_name = self._entity_to_helper(entity_id)
        
        try:
            if hasattr(self, 'state') and hasattr(self.state, 'set'):
                self.state.set(helper_name, '')
                return True
            elif self._hass:
                await self._hass.services.async_call(
                    'input_text',
                    'set_value',
                    {
                        'entity_id': helper_name,
                        'value': ''
                    }
                )
                return True
        except Exception as e:
            if self._logger:
                self._logger.error(f"Failed to delete: {e}", entity_id=entity_id)
        
        return False
    
    async def clear(self) -> None:
        """Очистить все состояния (требует сканирования)"""
        if self._logger:
            self._logger.warning("InputTextStore.clear() requires scanning all entities")


class DebouncedStateStore(StateStore):
    """
    Обёртка над другим StateStore которая добавляет дебаунс записей.
    
    Принцип работы:
    - save() кладёт данные в pending queue
    - Если прошло > debounce_sec с последней записи - сбрасываем в inner_store
    - flush() принудительно записывает всё
    
    Usage:
        file_store = FileStateStore("/path/to/state.json")
        debounced = DebouncedStateStore(file_store, debounce_sec=5.0)
        
        # При завершении работы
        await debounced.flush()
    """
    
    def __init__(self, inner_store: StateStore, debounce_sec: float = 5.0, logger=None):
        self._inner = inner_store
        self._debounce_sec = debounce_sec
        self._logger = logger
        
        self._pending: dict[str, dict] = {}
        self._last_write_time = 0.0
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
    
    async def _schedule_flush(self) -> None:
        """Запланировать фоновую запись"""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._background_flush())
    
    async def _background_flush(self) -> None:
        """Фоновая задача для записи pending данных"""
        while True:
            await asyncio.sleep(self._debounce_sec)
            
            async with self._lock:
                now = time.time()
                if self._pending and (now - self._last_write_time) >= self._debounce_sec:
                    # Записываем все pending
                    for entity_id, data in list(self._pending.items()):
                        await self._inner.save(entity_id, data)
                        del self._pending[entity_id]
                    self._last_write_time = now
                    
                    if self._logger:
                        self._logger.debug("DebouncedStateStore wrote pending data")
    
    async def save(self, entity_id: str, state_data: dict) -> bool:
        async with self._lock:
            self._pending[entity_id] = dict(state_data)
        
        await self._schedule_flush()
        
        if self._logger:
            self._logger.debug(f"DebouncedStateStore pending save for {entity_id}")
        
        return True
    
    async def load(self, entity_id: str) -> Optional[dict]:
        # Сначала проверяем pending
        async with self._lock:
            if entity_id in self._pending:
                return dict(self._pending[entity_id])
        
        # Затем загружаем из inner store
        return await self._inner.load(entity_id)
    
    async def load_all(self) -> dict[str, dict]:
        # Загружаем из inner store
        result = await self._inner.load_all()
        
        # Добавляем pending
        async with self._lock:
            result.update({k: dict(v) for k, v in self._pending.items()})
        
        return result
    
    async def delete(self, entity_id: str) -> bool:
        async with self._lock:
            if entity_id in self._pending:
                del self._pending[entity_id]
        
        return await self._inner.delete(entity_id)
    
    async def clear(self) -> None:
        async with self._lock:
            self._pending.clear()
        
        await self._inner.clear()
        
        if self._logger:
            self._logger.info("DebouncedStateStore cleared")
    
    async def flush(self) -> None:
        """
        Принудительная запись всех pending данных.
        Вызывать перед завершением работы.
        """
        async with self._lock:
            for entity_id, data in list(self._pending.items()):
                await self._inner.save(entity_id, data)
                del self._pending[entity_id]
            self._last_write_time = time.time()
        
        if self._logger:
            self._logger.info("DebouncedStateStore flushed")
