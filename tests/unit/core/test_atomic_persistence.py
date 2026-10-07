"""Атомарность записи и защита от потери данных при повреждении файла.

Блокер 2 продакшен-плана: пять хранилищ писали через `open(..., "w")` +
`json.dump`, то есть файл усекался **до** записи. Сбой питания в этот момент
оставлял его обрезанным или пустым; при следующем чтении возвращался `{}`, и
**следующая же запись перезаписывала файл пустым состоянием** — данные
исчезали бессрочно, единственным следом оставалась строка `WARNING`.

Проверки здесь двух сортов:

- **поведенческие** — повреждённый файл сохраняется целиком, а читающий код
  узнаёт о повреждении вместо молчаливого получения пустоты;
- **механические** — ни одно хранилище не содержит `open(..., "w")` для
  данных: иначе дефект вернётся тихо, без падения тестов.

Проверка «атомарно» на чтение кода бессильна: `os.replace` и `open("w")`
выглядят в коде похоже. Поэтому атомарность доказывается исполнением —
см. `TestAtomicWriteIsNeverPartiallyVisible`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import json
from pathlib import Path

import pytest

from core.persistence.atomic import (
    PersistenceCorruptedError,
    atomic_write_json,
    atomic_write_text,
    preserve_corrupt_file,
    read_json_preserving_corrupt,
)


class TestAtomicWriteIsNeverPartiallyVisible:
    """Файл никогда не должен наблюдаться в промежуточном состоянии.

    Ключевая проверка блокера: при ``open(..., "w")`` файл обрезается до
    того, как данные записаны, и в этом окне читатель видит пустой или
    обрезанный файл.

    Первая версия теста читала файл **после** завершения каждой записи. Так
    окно усечения не наблюдается никогда, и тест проходил даже на заведомо
    неатомарной реализации — то есть доказывал не то, что заявлял. Чтобы
    окно увидеть, чтение выполняется В МОМЕНТ, когда запись уже началась, но
    ещё не закончилась: для этого ``json.dump`` внутри хелпера задерживается
    на середине.
    """

    def test_reader_sees_whole_file_during_write(self, tmp_path: Path) -> None:
        """В момент незавершённой записи файл остаётся валидным и полным."""
        import threading

        target = tmp_path / "data.json"
        # Полезная нагрузка до записи — её читатель обязан увидеть целиком.
        original = {"payload": ["строка" * 200 for _ in range(50)]}
        atomic_write_json(target, original)

        write_started = threading.Event()
        release_write = threading.Event()
        real_dump = json.dump

        import core.persistence.atomic as atomic_module

        def slow_dump(data, handle, *args, **kwargs):
            # Сигнализируем, что запись началась, и ждём, пока читатель
            # посмотрит на файл именно в этот момент.
            write_started.set()
            release_write.wait(timeout=5)
            return real_dump(data, handle, *args, **kwargs)

        atomic_module.json.dump = slow_dump

        def writer():
            atomic_write_json(target, {"replacement": "x" * 100000})

        thread = threading.Thread(target=writer)
        thread.start()

        try:
            assert write_started.wait(timeout=5), "запись не началась"
            observed = json.loads(target.read_text(encoding="utf-8"))
        finally:
            release_write.set()
            thread.join(timeout=5)
            atomic_module.json.dump = real_dump

        assert observed == original, (
            "в момент незавершённой записи файл содержал не предыдущие данные, "
            f"а промежуточное состояние: {str(observed)[:120]}"
        )

    def test_failed_write_leaves_previous_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Неудачная запись не должна уничтожить прежнее содержимое.

        Отказ имитируется на ``os.replace`` — это последний шаг атомарной
        записи. Ошибку сериализации так не вызвать: в ``atomic_write_json``
        передан ``default=str``, поэтому несериализуемое значение
        превращается в строку, а не роняет запись.
        """
        target = tmp_path / "data.json"
        atomic_write_json(target, {"important": [1, 2, 3]})

        import core.persistence.atomic as atomic_module

        def boom(src, dst):
            raise OSError("диск отказал")

        monkeypatch.setattr(atomic_module.os, "replace", boom)

        with pytest.raises(OSError):
            atomic_write_json(target, {"round": 2})

        monkeypatch.undo()

        assert json.loads(target.read_text(encoding="utf-8")) == {"important": [1, 2, 3]}, (
            "после неудачной записи прежние данные должны были уцелеть"
        )

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        """Временные файлы не должны накапливаться."""
        for index in range(5):
            atomic_write_json(tmp_path / "data.json", {"round": index})

        leftovers = [p.name for p in tmp_path.iterdir() if ".tmp." in p.name]
        assert not leftovers, f"остались временные файлы: {leftovers}"

    def test_parent_directory_created(self, tmp_path: Path) -> None:
        """Отсутствующий каталог создаётся, а не роняет запись."""
        target = tmp_path / "nested" / "deep" / "data.json"

        atomic_write_json(target, {"ok": True})

        assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


class TestAtomicWriteText:
    """Манифест пишется как YAML — тоже атомарно."""

    def test_text_write_is_atomic_and_leaves_no_temp(self, tmp_path: Path) -> None:
        target = tmp_path / "manifest.yaml"

        atomic_write_text(target, "version: 1\n")

        assert target.read_text(encoding="utf-8") == "version: 1\n"
        assert not [p for p in tmp_path.iterdir() if ".tmp." in p.name]

    def test_failed_text_write_keeps_previous(self, tmp_path: Path) -> None:
        target = tmp_path / "manifest.yaml"
        atomic_write_text(target, "original: true\n")

        with pytest.raises(TypeError):
            atomic_write_text(target, 12345)  # type: ignore[arg-type]

        assert target.read_text(encoding="utf-8") == "original: true\n"


class TestCorruptedFileIsPreserved:
    """Повреждение не должно приводить к тихой потере данных."""

    def test_corrupted_file_moved_aside_with_full_content(self, tmp_path: Path) -> None:
        """Содержимое сохраняется целиком под суффиксом .corrupt-<ts>."""
        target = tmp_path / "data.json"
        target.write_text("{битое содержимое", encoding="utf-8")

        with pytest.raises(PersistenceCorruptedError):
            read_json_preserving_corrupt(target)

        backups = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
        assert len(backups) == 1, f"ожидалась одна копия, найдено: {backups}"
        assert backups[0].read_text(encoding="utf-8") == "{битое содержимое", (
            "копия должна содержать исходные данные целиком — иначе она "
            "бесполезна для восстановления"
        )

    def test_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        """Отсутствующий файл — это пустые данные, а не повреждение."""
        data, backup = read_json_preserving_corrupt(tmp_path / "нет.json")

        assert data == {}
        assert backup is None

    def test_valid_file_reads_without_backup(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text('{"a": 1}', encoding="utf-8")

        data, backup = read_json_preserving_corrupt(target)

        assert data == {"a": 1}
        assert backup is None

    def test_repeated_corruption_does_not_overwrite_backup(self, tmp_path: Path) -> None:
        """Два повреждения подряд — две копии, ранняя не затирается."""
        target = tmp_path / "data.json"

        target.write_text("первое", encoding="utf-8")
        with pytest.raises(PersistenceCorruptedError):
            read_json_preserving_corrupt(target)

        target.write_text("второе", encoding="utf-8")
        with pytest.raises(PersistenceCorruptedError):
            read_json_preserving_corrupt(target)

        contents = {
            p.read_text(encoding="utf-8") for p in tmp_path.iterdir() if ".corrupt-" in p.name
        }
        assert contents == {"первое", "второе"}, (
            f"обе копии должны сохраниться, найдено: {contents}"
        )

    def test_error_message_names_the_backup(self, tmp_path: Path) -> None:
        """Сообщение должно называть копию: иначе оператор её не найдёт."""
        target = tmp_path / "data.json"
        target.write_text("{битое", encoding="utf-8")

        with pytest.raises(PersistenceCorruptedError) as exc:
            read_json_preserving_corrupt(target)

        message = str(exc.value)
        assert ".corrupt-" in message, f"сообщение не называет копию: {message}"
        assert target.name in message, f"сообщение не называет исходный файл: {message}"

    def test_preserve_helper_returns_existing_path(self, tmp_path: Path) -> None:
        """Хелпер возвращает путь, который действительно существует."""
        target = tmp_path / "data.json"
        target.write_text("данные", encoding="utf-8")

        backup = preserve_corrupt_file(target)

        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == "данные"


class TestStorageDataIsNotTruncatedInPlace:
    """Ни одно хранилище не должно писать данные через `open(..., "w")`.

    Механическая проверка на возврат дефекта: иначе он вернётся тихо,
    без падения тестов, и обнаружится снова только потерей данных.
    """

    #: Модули, в которых данные пишутся на диск.
    WRITERS = (
        "core/persistence/devices.py",
        "core/persistence/sources.py",
        "core/persistence/manifest_store.py",
        "core/persistence/index_manager.py",
        "webui/app.py",
    )

    @pytest.mark.parametrize("relative_path", WRITERS)
    def test_module_uses_atomic_write(self, relative_path: str):
        """В модуле не должно быть прямой записи в файл через open(...,'w')."""
        import core

        root = Path(core.__file__).parent.parent
        source = (root / relative_path).read_text(encoding="utf-8")

        offenders = [
            (number, line.strip())
            for number, line in enumerate(source.splitlines(), 1)
            if "open(" in line and '"w"' in line
        ]

        assert not offenders, (
            f"{relative_path}: файл усекается до записи, данные теряются при "
            f"сбое. Найдено: {offenders}"
        )
