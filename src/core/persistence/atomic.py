"""Атомарная запись JSON и защита от потери данных при повреждении файла.

Введено после того, как аудит обнаружил, что пять хранилищ писали через
``open(..., "w")`` + ``json.dump``: файл усекался **до** записи, и сбой
питания в этот момент оставлял его обрезанным или пустым. При следующем
чтении возвращался ``{}``, и **следующая же запись перезаписывала файл
пустым состоянием** — все данные исчезали бессрочно, единственным следом
оставалась строка ``WARNING`` в журнале.

Проверено на ``DeviceSyncEventPersistence`` до правки: после повреждения
файла и одной новой записи в файле оставалась только новая запись, исходная
исчезла, копии повреждённого файла рядом не было.

Шаблон атомарной записи в проекте уже существовал (``StatePersistence``),
просто не был применён шире. Здесь он вынесен и исправлен: оригинал брал
блокировку на заменяемом inode, из-за чего взаимное исключение между
вызовами не работало.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


class PersistenceCorruptedError(RuntimeError):
    """Файл хранилища повреждён и не может быть перезаписан.

    Файл намеренно не трогают после обнаружения повреждения: перезапись
    уничтожила бы остатки данных (возможно, частично читаемые) без
    возможности восстановления. Пока файлы существуют с суффиксом
    ``.corrupt-<timestamp>``, запись запрещена — это вынуждает оператора
    принять решение, а не молча потерять данные.
    """


def atomic_write_json(path: Path, data: Any, *, indent: int | None = 2) -> None:
    """Записать JSON атомарно.

    Порядок: временный файл → ``flush`` → ``fsync`` → ``os.replace`` →
    ``fsync`` каталога. ``os.replace`` атомарен на POSIX и на Windows, в отличие
    от ``os.rename``, который на Windows не перезаписывает существующий файл.

    Args:
        path: Куда писать.
        data: Данные, сериализуемые в JSON.
        indent: Отступ для читаемости.

    Raises:
        OSError: Если запись или замена файла не удалась.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Уникальное имя: PID + микросекунды, чтобы параллельные процессы
    # (или две записи в одном) не столкнулись на одном temp-файле.
    temp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{time.time_ns()}")

    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=indent, ensure_ascii=False, default=str)
            handle.flush()
            # fsync до закрытия: иначе при сбое питания файл может оказаться
            # нулевым длиной, несмотря на успешный close().
            os.fsync(handle.fileno())

        os.replace(temp_path, path)

        # fsync каталога: без него запись имени файла может не попасть на диск
        # даже после успешного fsync содержимого.
        _fsync_directory(path.parent)
    finally:
        # Временный файл не должен остаться ни при успехе, ни при ошибке.
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)


def atomic_write_text(path: Path | str, text: str) -> None:
    """Записать текст атомарно.

    Нужна для файлов, которые пишутся не через ``json.dump``: манифест
    хранится в YAML, а он тоже терялся при сбое записи — файл усекался
    до того, как yaml успевал его заполнить.

    Args:
        path: Куда писать.
        text: Содержимое файла.

    Raises:
        OSError: Если запись или замена файла не удалась.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{time.time_ns()}")

    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    """Сбросить изменения каталога на диск.

    На Windows каталоги открыть для ``fsync`` нельзя, поэтому шаг пропускается:
    там атомарность обеспечивается ``os.replace``.
    """
    if sys.platform == "win32":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def read_json_preserving_corrupt(path: Path) -> tuple[Any, Path | None]:
    """Прочитать JSON, при повреждении сохранив файл целиком.

    Args:
        path: Файл для чтения.

    Returns:
        Кортеж ``(данные, копия_повреждённого)``. Если файл отсутствует или
        читается — ``(данные, None)``.

    **Что происходит с оригиналом.** Он перемещается в файл с суффиксом
    ``.corrupt-<timestamp>``, а по исходному пути больше ничего не лежит.
    Поэтому следующая запись создаёт файл заново — но содержимое повреждённого
    файла сохранено целиком и доступно для восстановления, а не затёрто пустым
    состоянием. Это ровно то поведение, которого не хватало: раньше
    «чтение вернуло пусто» немедленно превращалось в «файл перезаписан пустым».
    Само исключение останавливает вызывающий код, поэтому решение о потере
    данных остаётся за оператором, а не принимается молча.

    Raises:
        PersistenceCorruptedError: Файл существует, но не разбирается.
    """
    if not path.exists():
        return {}, None

    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle), None
    except json.JSONDecodeError as exc:
        backup = preserve_corrupt_file(path)
        raise PersistenceCorruptedError(
            f"Файл {path} повреждён ({exc}). Копия сохранена как {backup}. "
            f"Файл НЕ перезаписывается: сначала восстановите данные вручную "
            f"или удалите {backup.name} и {path.name}, чтобы начать с нуля."
        ) from exc


def preserve_corrupt_file(path: Path) -> Path:
    """Сохранить повреждённый файл рядом с уникальным суффиксом.

    Суффикс содержит время, чтобы несколько повреждений подряд не затирали
    друг друга.

    Returns:
        Путь к сохранённой копии.
    """
    backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}-{counter}")
        counter += 1
    try:
        os.replace(path, backup)
    except OSError:
        # Файл занят или недоступен — копируем содержимое, оригинал не трогаем.
        with contextlib.suppress(OSError):
            backup.write_bytes(path.read_bytes())
    return backup
