"""
State Persistence Module for Smart Home Platform.

This module provides state persistence for FSMs, allowing states to be
saved to a JSON file and restored on platform restart.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import sys
from pathlib import Path

from core.persistence.atomic import (
    PersistenceCorruptedError,
    atomic_write_json,
    file_lock,
    preserve_corrupt_file,
)
from core.persistence.paths import resolve_data_dir


# Platform-specific file locking imports
if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


# Каталог хранения состояний автоматов — рядом с прочими файлами данных
# платформы, а не в текущем рабочем каталоге (T013). Источник пути —
# ``paths.resolve_data_dir``, который читает DATA_PATH: иначе в контейнере
# файл писался внутрь слоя образа, а том монтировался в другой каталог
# (Known Issue #44).
DEFAULT_STORAGE_FILENAME = "state.json"


def default_storage_path() -> str:
    """Получить путь файла состояний по умолчанию.

    Returns:
        Путь к файлу состояний внутри каталога данных платформы.
    """
    return str(resolve_data_dir(None) / DEFAULT_STORAGE_FILENAME)


class StatePersistence:
    """
    Persists FSM states to a JSON file.

    This class handles saving and loading FSM states to/from a JSON file,
    enabling state recovery after platform restarts.

    Attributes:
        storage_path: Path to the JSON file where states are stored.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        """
        Initialize the state persistence manager.

        Args:
            storage_path: Path to the JSON file for storing states. По умолчанию —
                ``data/state.json``.
        """
        self.storage_path = Path(storage_path) if storage_path else Path(default_storage_path())
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Ensure the directory for the storage file exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _acquire_lock(self, f):
        """
        Acquire an exclusive lock on the file.

        Args:
            f: File object to lock.
        """
        if sys.platform == "win32":
            # Windows: use msvcrt.locking()
            # Lock a large region to cover the entire file
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1024 * 1024)
        else:
            # Linux/Unix: use fcntl.flock()
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _release_lock(self, f):
        """
        Release the lock on the file.

        Args:
            f: File object to unlock.
        """
        if sys.platform == "win32":
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1024 * 1024)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _load_data(self, lock_file=None) -> dict:
        """
        Load existing data from the JSON file.

        Args:
            lock_file: Optional file object that is already locked.

        Returns:
            dict: The current data in the storage file, or empty dict if not exists.
        """
        if not self.storage_path.exists():
            return {}

        try:
            with open(self.storage_path, encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                # Пустой файл — не повреждение, а законное состояние: свежая
                # установка или файл, обрезанный до нуля сбоем питания. Раньше
                # он молча превращался в {}, и данные терялись; теперь
                # отличаем «пусто» от «испорчено», чтобы чистая установка не
                # падала с ошибкой.
                return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError as exc:
            # Раньше здесь возвращался пустой словарь, и следующая же запись
            # перезаписывала файл пустым состоянием — состояния автоматов
            # исчезали бессрочно. Теперь файл сохраняется целиком, а вызывающий
            # узнаёт о повреждении.
            backup = preserve_corrupt_file(self.storage_path)
            raise PersistenceCorruptedError(
                f"Файл {self.storage_path} повреждён ({exc}); копия: {backup}. "
                f"Данные не перезаписываются — восстановите их вручную."
            ) from exc
        except OSError:
            return {}

    def _save_data(self, data: dict) -> None:
        """Сохранить данные через общий атомарный хелпер.

        Args:
            data: Данные для сохранения.
        """
        self._ensure_storage_dir()
        with file_lock(self.storage_path):
            atomic_write_json(self.storage_path, data)

    def save_state(self, entity_id: str, state: str, context: dict) -> None:
        """Сохранить состояние автомата.

        Запись идёт через общий атомарный хелпер :func:`atomic_write_json`
        (temp → fsync → ``os.replace`` → fsync каталога), а взаимное
        исключение берётся на **отдельный** файл ``<state>.lock``.

        Раньше замок брался на сам файл состояний, который тут же подменялся
        ``os.rename``: после подстановки нового inode замок оказывался на
        файле, которого больше нет, и взаимное исключение не работало, хотя
        докстринг утверждал обратное.

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.
            context: Контекст состояния.
        """
        self._ensure_storage_dir()

        with file_lock(self.storage_path):
            data = self._load_data()
            data[entity_id] = {"state": state, "context": context}
            atomic_write_json(self.storage_path, data)

    async def save_state_async(self, entity_id: str, state: str, context: dict) -> None:
        """Сохранить состояние, не блокируя event loop.

        ``save_state`` синхронный и делает ``fsync`` — на медленном диске это
        заметная пауза. Движок вызывал его прямо из корутины перехода, то есть
        каждый переход FSM останавливал event loop на время записи.

        Args:
            entity_id: Идентификатор автомата.
            state: Имя состояния.
            context: Контекст состояния.
        """
        await asyncio.to_thread(self.save_state, entity_id, state, context)

    def load_state(self, entity_id: str) -> tuple[str, dict] | None:
        """
        Load a saved FSM state from the storage file.

        Args:
            entity_id: The unique identifier of the FSM entity.

        Returns:
            Optional[Tuple[str, dict]]: A tuple of (state, context) if found,
                                        None if no saved state exists.
        """
        data = self._load_data()
        if entity_id not in data:
            return None

        entry = data[entity_id]
        state = entry.get("state")
        context = entry.get("context", {})

        if state is None:
            return None

        return (state, context)

    def clear_state(self, entity_id: str) -> None:
        """
        Clear the saved state for an entity.

        Args:
            entity_id: The unique identifier of the FSM entity.
        """
        data = self._load_data()
        if entity_id in data:
            del data[entity_id]
            self._save_data(data)

    def clear_all(self) -> None:
        """Clear all saved states."""
        if self.storage_path.exists():
            self.storage_path.unlink()

    def save_all(self, states: dict) -> None:
        """
        Save all FSM states to the storage file at once.

        This method is useful for graceful shutdown when you need to persist
        all current states in a single operation.

        Args:
            states: Dictionary mapping entity_id to (state, context) tuples.
        """
        data = {}
        for entity_id, (state, context) in states.items():
            data[entity_id] = {"state": state, "context": context}
        self._save_data(data)
