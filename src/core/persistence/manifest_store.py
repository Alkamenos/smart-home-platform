"""Хранилище манифеста: загрузка, сохранение с резервной копией и откат.

Живёт в core, потому что манифест — конфигурация платформы (конституция V),
и его должен писать любой путь добавления устройств: веб-интерфейс,
CLI-импорт и мастер обнаружения. WebUI импортирует хранилище отсюда,
поэтому «Reload» в интерфейсе и запись из сервисов не расходятся.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import copy
from typing import Any

import yaml
from loguru import logger

from src.core.models.manifest import Manifest


class ManifestStore:
    """Хранилище манифеста с откатом (undo).

    Держит актуальное состояние манифеста, снимок до последнего
    сохранения и признак несохранённых изменений. Единственный
    владелец записи манифеста на диск.

    Модель манифеста передаётся снаружи: веб-интерфейс работает со
    своей зеркальной моделью ``webui.models.ManifestModel``, CLI и ядро —
    с канонической ``core.models.manifest.Manifest``. Форма YAML у них
    одинаковая, а тип у каждого потребителя свой.
    """

    def __init__(self, path: str, model_type: type[Any] = Manifest) -> None:
        """Создаёт хранилище манифеста.

        Args:
            path: Путь к YAML-файлу манифеста.
            model_type: Класс модели манифеста для загрузки и валидации.
        """
        self.path = path
        self.model_type = model_type
        self.current: Any | None = None
        self.backup: Any | None = None
        self.has_unsaved_changes: bool = False

    def load(self) -> Any:
        """Загружает манифест из YAML-файла.

        Returns:
            Загруженная и проверенная модель манифеста.

        Raises:
            FileNotFoundError: Если файла манифеста нет.
            ValidationError: Если манифест некорректен.
        """
        with open(self.path) as f:
            data = yaml.safe_load(f) or {}

        self.current = self.model_type(**data)
        # Снимок состояния на момент загрузки: в него попадёт .bak при первом
        # сохранении. Раньше снимка не было, и первое сохранение клало в
        # резервную копию уже изменённый манифест — откатываться было некуда.
        self.backup = copy.deepcopy(self.current)
        self.has_unsaved_changes = False
        logger.info(f"Манифест загружен из {self.path}")
        return self.current

    def save(self) -> None:
        """Сохраняет манифест в YAML, предварительно сделав снимок.

        Raises:
            ValueError: Если манифест не загружен.
        """
        if self.current is None:
            raise ValueError("No manifest loaded")

        # Снимок состояния до записи — основа для отката
        backup_path = f"{self.path}.bak"
        with open(backup_path, "w") as f:
            if self.backup:
                yaml.dump(self.backup.model_dump(), f, default_flow_style=False, sort_keys=False)
            else:
                # Снимка ещё нет — сохраняем текущее состояние
                yaml.dump(self.current.model_dump(), f, default_flow_style=False, sort_keys=False)

        # Актуальное состояние
        with open(self.path, "w") as f:
            yaml.dump(self.current.model_dump(), f, default_flow_style=False, sort_keys=False)

        self.backup = copy.deepcopy(self.current)
        self.has_unsaved_changes = False
        logger.info(f"Манифест сохранён в {self.path}, резервная копия: {backup_path}")

    def revert(self) -> Any:
        """Откатывает манифест к последнему сохранённому состоянию.

        Returns:
            Модель манифеста после отката.

        Raises:
            ValueError: Если манифест не загружен.
        """
        if self.current is None:
            raise ValueError("No manifest loaded")

        if self.backup is not None:
            self.current = copy.deepcopy(self.backup)
        else:
            # Снимка нет — перечитываем файл
            self.load()

        self.has_unsaved_changes = False
        logger.info("Манифест откатан к сохранённому состоянию")
        return self.current

    def mark_changed(self) -> None:
        """Отмечает манифест как имеющий несохранённые изменения."""
        self.has_unsaved_changes = True
