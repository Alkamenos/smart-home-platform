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

from core.models.manifest import Manifest
from core.persistence.atomic import atomic_write_text


class ManifestShrinkError(RuntimeError):
    """Запись манифеста потеряла часть описания дома.

    Отдельный тип нужен, чтобы отказ был различим: «файл не записали» и «запись
    уменьшила состав дома» — разные вещи, и молчать о второй нельзя. Возникает
    при попытке сохранить модель, в которой потеряны комнаты или устройства,
    бывшие на диске, без явного разрешения на удаление (Known Issue #88).
    """


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
        # Глубина пачки и разрешение на удаление, накопленное внутри неё.
        self._batch_depth: int = 0
        self._batch_allow_removal: bool = False

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

    def batch(self) -> Any:
        """Отложить записи до конца блока: пачка изменений — один файл.

         Применение пачки устройств сохраняло манифест на каждое устройство — три
        надцать записей за секунду, и каждая перетирала резервную копию. Откатываться
         после этого было некуда (Known Issue #88).

         Returns:
             Контекстный менеджер, откладывающий запись до выхода.
        """
        return self

    def __enter__(self) -> ManifestStore:
        """Войти в пачку отложенных записей.

        Returns:
            То же хранилище — вложенные блоки считаются одним.
        """
        self._batch_depth += 1
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Выйти из пачки и записать один раз, если менялось.

        Args:
            exc_type: Тип исключения, если оно было.
            exc: Само исключение.
            tb: След стека.
        """
        self._batch_depth -= 1
        if self._batch_depth > 0 or exc_type is not None:
            return
        if not self.has_unsaved_changes or self.current is None:
            return
        self._write(allow_removal=self._batch_allow_removal)

    def save(self, *, allow_removal: bool = False) -> None:
        """Сохраняет манифест в YAML, предварительно сделав снимок.

        Args:
            allow_removal: Разрешить запись, при которой из описания дома
                исчезают комнаты или устройства. По умолчанию запрещено: тихое
                уменьшение состава дома означает, что часть дома молча выпала из
                автоматики (Known Issue #88). Явное удаление устройства —
                единственный законный повод.

        Raises:
            ValueError: Если манифест не загружен.
            ManifestShrinkError: Если запись потеряла бы комнаты или устройства.
        """
        if self.current is None:
            raise ValueError("No manifest loaded")

        if not allow_removal:
            self._refuse_shrinking()

        if self._batch_depth > 0:
            # Внутри пачки файл не трогаем: тринадцать записей подряд перетирали
            # резервную копию, и откатываться было некуда (Known Issue #88).
            self.has_unsaved_changes = True
            self._batch_allow_removal = self._batch_allow_removal or allow_removal
            return

        self._write(allow_removal=allow_removal)

    def _write(self, *, allow_removal: bool) -> None:
        """Записать манифест на диск вместе с резервной копией.

        Args:
            allow_removal: Разрешена ли запись с уменьшением описания дома.

        Raises:
            ValueError: Если манифест не загружен.
        """
        manifest = self.current
        if manifest is None:
            raise ValueError("No manifest loaded")
        dumped = yaml.dump(
            manifest.model_dump(),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        # Запись без изменений не трогает ни файл, ни резервную копию: иначе
        # `.bak` перезаписывался бы тем же содержимым и точка отката исчезала.
        # Сравнение по смыслу, а не по тексту: формат дампа (порядок ключей,
        # переносы) не должен превращать обычную проверку в запись файла.
        if self._same_as_disk():
            self.has_unsaved_changes = False
            return

        # Снимок состояния до записи — основа для отката.
        # allow_unicode в обоих дампах: кириллица в манифесте — норма, а не
        # редкость, и escape-последовательности делают файл нечитаемым для
        # человека, хотя валидатор и загрузчик такие последовательности понимают.
        backup_path = f"{self.path}.bak"
        snapshot = self.backup or manifest
        atomic_write_text(
            backup_path,
            yaml.dump(
                snapshot.model_dump(),
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            ),
        )

        # Актуальное состояние
        atomic_write_text(self.path, dumped)

        self.backup = copy.deepcopy(self.current)
        self.has_unsaved_changes = False
        logger.info(f"Манифест сохранён в {self.path}, резервная копия: {backup_path}")

    def _same_as_disk(self) -> bool:
        """Совпадает ли сохраняемый манифест с содержимым файла.

        Returns:
            True, если записывать нечего.
        """
        manifest = self.current
        if manifest is None:
            return False
        try:
            on_disk = self._read_raw()
        except (OSError, ValueError):
            # Файла нет или он не разбирается — записываем: проверка не должна
            # мешать записи, которого ждут.
            return False
        # Сравниваются две разобранные модели, а не текст и не выборочные поля:
        # разобранная модель дополняет значения по умолчанию, поэтому «просто
        # совпадение» без разбора расходилось бы всегда. Выборочное сравнение
        # (только комнаты и идентификаторы) было хуже: переименование светильника
        # и перенос между комнатами оно считало отсутствием изменений, и правка из
        # интерфейса молча не доходила до файла (Known Issue #88).
        try:
            disk_model = self.model_type(**on_disk)
        except Exception:  # noqa: BLE001 — модель может не принять файл, пишем
            return False
        return disk_model.model_dump() == manifest.model_dump()

    def _refuse_shrinking(self) -> None:
        """Отказать в записи, если из описания дома что-то пропало.

        Raises:
            ManifestShrinkError: Если на диске есть комнаты или устройства,
                которых нет в сохраняемой модели.
        """
        on_disk = self._read_raw()
        if not on_disk:
            return
        manifest = self.current
        if manifest is None:
            return
        incoming = manifest.model_dump()
        lost_rooms = _room_ids(on_disk) - _room_ids(incoming)
        lost_devices = _device_ids(on_disk) - _device_ids(incoming)
        if lost_rooms or lost_devices:
            raise ManifestShrinkError(
                "Запись манифеста уменьшила описание дома: "
                f"пропали комнаты {sorted(lost_rooms)}, устройства {sorted(lost_devices)}. "
                "Это не молчаливое изменение, а потеря части дома из автоматики; "
                "если удаление задумано, повторите с allow_removal=True "
                "(Known Issue #88)"
            )

    def reload_into(self, target: Any) -> None:
        """Перечитывает файл и обновляет существующий объект манифеста на месте.

        Подмена объекта не годится: `Container`, `EventRouter`, фабрика машин
        состояний и `DeviceLifecycleService` держат ссылку именно на него, и
        после подмены все они продолжали бы работать с прежней копией — reload
        отвечал бы успехом и ничего бы не менял (Known Issue #68). Поэтому
        содержимое заливается в тот же экземпляр.

        Сначала файл разбирается во временный объект: если разбор упадёт, цель
        останется нетронутой. Частично применённый манифест хуже отказа.

        Args:
            target: Модель манифеста, обновляемая на месте.

        Raises:
            ValueError: Если файл не удалось разобрать.
        """
        fresh = self.model_type(**self._read_raw())
        target.__dict__.update(fresh.__dict__)
        self.current = target
        self.backup = copy.deepcopy(target)
        self.has_unsaved_changes = False
        logger.info(f"Манифест перечитан из {self.path} в существующий объект")

    def _read_raw(self) -> dict[str, Any]:
        """Читает и разбирает файл манифеста без изменения состояния хранилища.

        Returns:
            Словарь данных манифеста.

        Raises:
            FileNotFoundError: Если файла нет.
            ValidationError: Если манифест некорректен.
        """
        with open(self.path) as f:
            return yaml.safe_load(f) or {}

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


def _room_ids(data: dict[str, Any]) -> set[str]:
    """Идентификаторы комнат в данных манифеста.

    Args:
        data: Разобранный манифест.

    Returns:
        Множество идентификаторов.
    """
    return {str(room.get("id")) for room in (data.get("rooms") or []) if room.get("id")}


def _sensor_ids(data: dict[str, Any]) -> set[tuple[str, str, str]]:
    """Роли датчиков комнат в данных манифеста.

    Args:
        data: Разобранный манифест.

    Returns:
        Множество троек «комната — роль — сущность».
    """
    return {
        (str(room.get("id")), str(role), str(entity))
        for room in (data.get("rooms") or [])
        for role, entity in (room.get("sensors") or {}).items()
    }


def _device_ids(data: dict[str, Any]) -> set[str]:
    """Идентификаторы устройств в данных манифеста.

    Args:
        data: Разобранный манифест.

    Returns:
        Множество идентификаторов.
    """
    return {
        str(device.get("id"))
        for room in (data.get("rooms") or [])
        for device in (room.get("devices") or [])
        if device.get("id")
    }
