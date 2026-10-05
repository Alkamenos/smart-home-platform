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
from collections.abc import Iterator
from pathlib import Path
from typing import Any


if sys.platform == "win32":  # pragma: no cover - ветка платформы
    import msvcrt
else:
    import fcntl


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


def atomic_write_text(path: Path | str, text: str, mode: int | None = None) -> None:
    """Записать текст атомарно.

    Нужна для файлов, которые пишутся не через ``json.dump``: манифест
    хранится в YAML, а он тоже терялся при сбое записи — файл усекался
    до того, как yaml успевал его заполнить.

    Args:
        path: Куда писать.
        text: Содержимое файла.
        mode: Права на файл, например ``0o600`` для секретов. Выставляются на
            временном файле **до** записи содержимого: иначе секрет успевает
            появиться читаемым всеми. Если не задано, действуют права по
            умолчанию.

    Raises:
        OSError: Если запись или замена файла не удалась.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{time.time_ns()}")

    try:
        if mode is not None:
            # Сначала создать пустой файл и выставить права, и только потом
            # писать содержимое. Обратный порядок оставляет окно, в котором
            # секрет доступен всем, кто может читать каталог.
            temp_path.touch()
            os.chmod(temp_path, mode)

        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)


@contextlib.contextmanager
def file_lock(path: Path | str) -> Iterator[None]:
    """Взаимное исключение через отдельный файл-замок.

    Замок берётся на **отдельный** файл ``<данные>.lock``, а не на сам файл
    данных. Причина: атомарная запись подменяет файл через ``os.replace``, то
    же самое делал прежний код через ``os.rename``. Замок, взятый на старом
    inode, после подстановки нового оказывается на файле, которого больше
    нет, — взаимное исключение перестаёт работать, хотя докстринг утверждал
    обратное. Побочный файл никогда не заменяется, поэтому его inode постоянен.

    Args:
        path: Путь к файлу данных. Замок будет на ``path`` с суффиксом
            ``.lock``.

    Yields:
        Ничего — блокировка действует, пока выполняется тело ``with``.
    """
    target = Path(path)
    lock_path = target.with_name(f"{target.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    handle = open(lock_path, "a+")  # noqa: SIM115 - освобождается в finally
    try:
        if sys.platform == "win32":
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1024 * 1024)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1024 * 1024)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


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
            content = handle.read()
        if not content.strip():
            # Пустой файл — не повреждение, а законное состояние (свежая
            # установка либо файл, обрезанный до нуля сбоем питания). Если
            # считать это повреждением, чистая установка падала бы с ошибкой.
            return {}, None
        return json.loads(content), None
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
