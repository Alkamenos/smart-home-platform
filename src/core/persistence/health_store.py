"""Хранилище проблем дома: активные, закрытые и состояние уведомления.

Файл небольшой, но его потеря означает потерю истории и повторные уведомления
после перезапуска. Поэтому запись атомарная: временный файл рядом и
``os.replace``, как у состояния автоматов.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.persistence.paths import resolve_data_dir


logger = get_logger(__name__)

#: Версия схемы файла. Чужую версию не читаем молча: пишем предупреждение.
SCHEMA_VERSION = 1

#: Имя файла в DATA_PATH.
DEFAULT_FILENAME = "health_problems.json"


def default_health_path() -> Path:
    """Путь файла проблем по умолчанию.

    Returns:
        ``DATA_PATH/health_problems.json``.
    """
    return resolve_data_dir(None) / DEFAULT_FILENAME


def empty_state() -> dict[str, Any]:
    """Пустое состояние хранилища.

    Returns:
        Словарь с версией, пустыми списками и состоянием уведомления.
    """
    return {
        "version": SCHEMA_VERSION,
        "problems": [],
        "closed": [],
        "notification": {},
        "expectations": {},
    }


class HealthStore:
    """Читать и атомарно сохранять состояние здоровья дома.

    Args:
        path: Путь файла; по умолчанию ``DATA_PATH/health_problems.json``.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_health_path()

    def load(self) -> dict[str, Any]:
        """Прочитать состояние.

        Повреждённый файл не должен ронять обход: возвращаем пустое состояние и
        пишем предупреждение, чтобы потеря истории была видна.

        Returns:
            Состояние хранилища.
        """
        if not self.path.exists():
            return empty_state()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"Здоровье дома: файл {self.path} не прочитан: {exc}")
            return empty_state()
        if not isinstance(raw, dict):
            logger.warning(f"Здоровье дома: файл {self.path} не словарь")
            return empty_state()
        version = raw.get("version")
        if version != SCHEMA_VERSION:
            logger.warning(
                f"Здоровье дома: версия схемы {version!r} не поддерживается "
                f"(ожидалась {SCHEMA_VERSION}); начинаю с пустого состояния"
            )
            return empty_state()
        state = empty_state()
        for key in ("problems", "closed", "notification", "expectations"):
            value = raw.get(key)
            if key in ("problems", "closed"):
                state[key] = list(value) if isinstance(value, list) else []
            elif isinstance(value, dict):
                state[key] = value
        return state

    def save(self, state: dict[str, Any]) -> None:
        """Атомарно записать состояние.

        Args:
            state: Словарь состояния; версия проставляется здесь.

        Returns:
            Ничего.
        """
        payload = dict(state)
        payload["version"] = SCHEMA_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise
