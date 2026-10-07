"""Хранение факта последнего ручного действия.

Факт переживает перезапуск, потому что блокировка должна работать и после него:
перезапуск — обычное дело, и именно тогда жилец обычно и проверяет, работает ли
«ничего не помогает». Сбрасывать блокировку при старте — значит оставлять дыру
именно там, где её заметят.

Почему отдельный файл, а не состояние автоматов
------------------------------------------------

`state.json` перезаписывается при горячей перезагрузке манифеста. Факт ручного
действия там потерялся бы ровно тогда, когда он нужнее всего, — а ещё он не
автомат, и хранить его среди состояний автоматов значило бы смешать два разных
по смыслу факта в одном файле.

Что хранится
------------

Только последнее ручное действие по каждому устройству. История управления
ведёт журнал переходов; второй источник правды о том, когда и как устройством
управляли, разошёлся бы с ним при первом же расхождении.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.persistence.atomic import atomic_write_json
from core.persistence.paths import resolve_data_dir


logger = logging.getLogger(__name__)

#: Имя файла в каталоге данных.
MANUAL_CONTROL_FILENAME = "manual_control.json"


class ManualControlStore:
    """Хранилище последнего ручного действия по каждому устройству.

    Запись атомарная: оборванный во время сбоя питания файл не должен
    превратить последнее действие жильца в потерю — иначе после перезапуска
    автоматика вернёт свет, который человек только что выключил.

    Attributes:
        data_dir: Каталог данных.
        file_path: Путь к файлу с фактами.
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        """Создать хранилище.

        Args:
            data_dir: Каталог данных; по умолчанию разрешается через ``DATA_PATH``.
        """
        self.data_dir = resolve_data_dir(data_dir)
        self.file_path = self.data_dir / MANUAL_CONTROL_FILENAME

    def load(self) -> dict[str, dict[str, Any]]:
        """Прочитать сохранённые факты.

        Отсутствие или повреждение файла означают «фактов нет», а не ошибку:
        платформа обязана подниматься и без них, иначе один оборванный JSON
        потребует вмешательства внутрь тома.

        Returns:
            Словарь «устройство → факт»; пустой, если читать нечего.
        """
        try:
            raw = self.file_path.read_text(encoding="utf-8")
        except OSError:
            return {}

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "Файл ручных действий не разобран (%s): блокировка не восстановлена",
                self.file_path,
            )
            return {}

        if not isinstance(data, dict):
            logger.warning(
                "Файл ручных действий имеет неожиданный вид (%s): ожидался объект",
                self.file_path,
            )
            return {}

        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def save(self, records: dict[str, dict[str, Any]]) -> bool:
        """Записать факты.

        Args:
            records: Словарь «устройство → факт».

        Returns:
            True, если запись состоялась.
        """
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.file_path, records)
        except OSError as exc:
            logger.warning(
                "Не удалось сохранить факты ручных действий (%s): блокировка не "
                "переживёт перезапуск",
                exc,
            )
            return False
        return True
