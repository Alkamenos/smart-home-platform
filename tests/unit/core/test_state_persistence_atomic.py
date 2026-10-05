"""StatePersistence: атомарность, блокировка по отдельному файлу, отсутствие блокировки event loop.

Продолжение Блокера 2. `StatePersistence` была единственным хранилищем с
атомарной записью, но у неё были две собственные ошибки:

1. **Замок брался на заменяемый inode.** `fcntl.flock` вызывался на самом файле
   состояний, который тут же подменялся `os.rename`. После подстановки нового
   inode замок оказывался на файле, которого больше нет, — взаимное
   исключение не работало, хотя докстринг утверждал обратно.
2. **`fsync` выполнялся в event loop.** `save_state` синхронный, а движок вызывал
   его прямо из корутины перехода, то есть каждый переход FSM останавливал
   цикл на время записи.

Обе исправлены: замок перенесён на отдельный файл `<state>.lock` (его inode
постоянен), добавлен `save_state_async` с выносом в поток.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import threading
from pathlib import Path

import pytest

from core.persistence.atomic import PersistenceCorruptedError, file_lock
from core.persistence.state_persistence import StatePersistence


@pytest.fixture
def storage(tmp_path: Path) -> StatePersistence:
    return StatePersistence(tmp_path / "state.json")


class TestLockIsOnSeparateFile:
    """Замок обязан быть на файле, который никогда не подменяется."""

    def test_lock_file_is_distinct_from_data_file(self, storage: StatePersistence):
        """Файл-замок не совпадает с файлом данных."""
        storage.save_state("light.test", "ON", {})

        lock_file = storage.storage_path.with_name(f"{storage.storage_path.name}.lock")
        assert lock_file.exists(), "файл-замок должен быть создан"
        assert lock_file != storage.storage_path

    def test_lock_file_survives_data_file_replacement(self, storage: StatePersistence):
        """Замена файла данных не должна уводить замок в пустоту.

        Прежний механизм держал flock на самом файле состояний. Каждая запись
        подменяла этот файл новым inode — и блокировка указывала на уже
        несуществующий файл, то есть взаимное исключение исчезало после первой
        же записи. Здесь inode файла-замка обязан быть постоянным.
        """
        storage.save_state("light.before", "ON", {})
        lock_file = storage.storage_path.with_name(f"{storage.storage_path.name}.lock")
        inode_before = lock_file.stat().st_ino

        for index in range(5):
            storage.save_state(f"light.{index}", "OFF", {})

        assert lock_file.stat().st_ino == inode_before, (
            "файл-замок подменили — блокировка снова указывает в пустоту"
        )


class TestMutualExclusionReallyWorks:
    """Проверка конкуренции настоящими потоками, а не моками."""

    def test_parallel_writes_keep_every_entity(self, tmp_path: Path):
        """Параллельные записи не теряют ни одну сущность.

        Read-modify-write без защиты: каждый поток читает файл, добавляет
        свою запись и пишет обратно. Без замка теряются все, кроме последней.
        """
        persistence = StatePersistence(tmp_path / "state.json")
        threads_count = 12
        errors: list[BaseException] = []
        barrier = threading.Barrier(threads_count)

        def writer(index: int) -> None:
            try:
                barrier.wait(timeout=10)
                persistence.save_state(f"light.{index}", "ON", {"n": index})
            except BaseException as exc:  # noqa: BLE001 - собираем в список
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(threads_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert not errors, f"потоки завершились с ошибками: {errors[:3]}"
        data = json.loads(persistence.storage_path.read_text(encoding="utf-8"))
        assert len(data) == threads_count, (
            f"ожидалось {threads_count} сущностей, сохранилось {len(data)} — "
            f"часть записей потеряна, то есть read-modify-write не защищён"
        )

    def test_file_lock_is_really_exclusive(self, tmp_path: Path):
        """Два потока не могут одновременно войти в file_lock."""
        target = tmp_path / "data.json"
        inside = 0
        overlaps = 0
        guard = threading.Lock()
        stop = threading.Event()

        def worker() -> None:
            nonlocal inside, overlaps
            while not stop.is_set():
                with file_lock(target):
                    with guard:
                        inside += 1
                        if inside > 1:
                            overlaps += 1
                    # Держим замок, чтобы второму потоку было что ловить
                    stop.wait(0.001)
                    with guard:
                        inside -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        stop.wait(0.2)
        stop.set()
        for thread in threads:
            thread.join(timeout=5)

        assert overlaps == 0, (
            f"замок не исключающий: {overlaps} раз два потока были внутри одновременно"
        )


class TestNoBlockingOfEventLoop:
    """Сохранение состояния не должно останавливать event loop."""

    @pytest.mark.asyncio
    async def test_save_state_async_does_not_block_loop(self, storage: StatePersistence) -> None:
        """Пока идёт сохранение, другие задачи цикла продолжают выполняться.

        Проверка именно параллельности: если `save_state` вызвать прямо из
        корутины, он заблокирует цикл на время `fsync`, и счётчик задач не
        сдвинется. Замер конечен: полная остановка цикла была бы зависанием
        теста, а не его падением.
        """
        ticks = 0
        done = False

        async def ticker() -> None:
            nonlocal ticks
            while not done:
                ticks += 1
                await asyncio.sleep(0)

        counter = asyncio.ensure_future(ticker())
        for index in range(20):
            await storage.save_state_async(f"light.{index}", "ON", {"i": index})
        done = True
        await counter

        assert ticks > 0, (
            "event loop не двигался во время сохранений — значит save_state "
            "выполнялся в корутине и блокировал цикл на fsync"
        )

    @pytest.mark.asyncio
    async def test_save_state_async_writes_the_same_data(self, storage: StatePersistence) -> None:
        """Асинхронный путь пишет те же данные, что и синхронный."""
        await storage.save_state_async("light.a", "ON", {"v": 1})
        await storage.save_state_async("light.b", "OFF", {"v": 2})

        data = json.loads(storage.storage_path.read_text(encoding="utf-8"))
        assert data["light.a"] == {"state": "ON", "context": {"v": 1}}
        assert data["light.b"] == {"state": "OFF", "context": {"v": 2}}

    @pytest.mark.asyncio
    async def test_engine_style_sequential_transitions_persist_all(
        self, storage: StatePersistence
    ) -> None:
        """Последовательность переходов сохраняется целиком."""
        for index in range(10):
            await storage.save_state_async(f"light.kitchen_{index}", "ON", {})

        data = json.loads(storage.storage_path.read_text(encoding="utf-8"))
        assert len(data) == 10


class TestCorruptedAndEmptyFiles:
    """Повреждение и пустой файл — разные вещи."""

    def test_empty_file_is_not_treated_as_corrupted(self, tmp_path: Path):
        """Пустой файл — законное состояние, а не повреждение.

        Пустой файл получается на свежей установке и после обрезания сбоем
        питания. Если считать это повреждением, чистая установка падала бы с
        ошибкой, и оператору пришлось бы удалять файл вручную ради пустого
        хранилища.
        """
        path = tmp_path / "state.json"
        path.write_text("", encoding="utf-8")
        persistence = StatePersistence(path)

        # Не должно бросить
        persistence.save_state("light.test", "ON", {})
        assert persistence.load_state("light.test") == ("ON", {})

    def test_whitespace_only_file_is_not_corrupted(self, tmp_path: Path):
        """Файл из одних пробелов — то же пустое состояние."""
        path = tmp_path / "state.json"
        path.write_text("   \n\t ", encoding="utf-8")
        persistence = StatePersistence(path)

        persistence.save_state("light.test", "ON", {})

        assert persistence.load_state("light.test") == ("ON", {})

    def test_corrupted_file_raises_and_is_preserved(self, tmp_path: Path):
        """Повреждённый файл сохраняется целиком, вызывающий узнаёт."""
        path = tmp_path / "state.json"
        path.write_text('{"broken": ', encoding="utf-8")
        persistence = StatePersistence(path)

        with pytest.raises(PersistenceCorruptedError):
            persistence.save_state("light.test", "ON", {})

        backups = list(tmp_path.glob("state.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == '{"broken": '

    def test_previous_entry_survives_new_save(self, storage: StatePersistence) -> None:
        """Новая запись не теряет предыдущие — это и есть read-modify-write."""
        storage.save_state("light.first", "ON", {})
        storage.save_state("light.second", "OFF", {})

        assert storage.load_state("light.first") == ("ON", {})
        assert storage.load_state("light.second") == ("OFF", {})
