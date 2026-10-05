"""Каталог данных платформы определяется `DATA_PATH`, а не относительным путём.

Known Issue #44: `DATA_PATH` был объявлен в `deploy/docker/Dockerfile` и
`docker-compose.prod.yml`, но не читался ни одной строкой Python. Все
хранилища использовали литерал `"data"`, который при `WORKDIR /app`
разрешался в `/app/data` — внутри слоя контейнера, тогда как том
монтировался в `/data/behavioral_platform`. Проверено запуском: созданный
источник исчезал после `docker compose down && up -d`.

Тест ловит возврат ошибки двумя независимыми способами, потому что
проверка на чтение кода бессильна: литерал `"data"` и `DATA_PATH` могут
сосуществовать, и пока не будет **исполнено** создание хранилища, дефект
не виден.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from pathlib import Path

import pytest

from core.persistence.paths import DEFAULT_DATA_DIR, resolve_data_dir


class TestResolveDataDir:
    """Разрешение пути каталога данных."""

    def test_env_variable_wins_over_relative_default(self, monkeypatch: pytest.MonkeyPatch):
        """DATA_PATH из окружения имеет приоритет над путём по умолчанию."""
        monkeypatch.setenv("DATA_PATH", "/srv/shp-data")

        assert resolve_data_dir(None) == Path("/srv/shp-data")

    def test_falls_back_to_relative_default(self, monkeypatch: pytest.MonkeyPatch):
        """Без переменной окружения поведение прежнее — `data`."""
        monkeypatch.delenv("DATA_PATH", raising=False)

        assert resolve_data_dir(None) == Path(DEFAULT_DATA_DIR) == Path("data")

    def test_explicit_argument_has_priority_over_env(self, monkeypatch: pytest.MonkeyPatch):
        """Явно переданный путь важнее переменной окружения.

        Иначе нельзя было бы указать каталог вручную — в тестах, утилитах и
        миграциях.
        """
        monkeypatch.setenv("DATA_PATH", "/srv/shp-data")

        assert resolve_data_dir("/tmp/explicit") == Path("/tmp/explicit")

    def test_empty_env_variable_ignored(self, monkeypatch: pytest.MonkeyPatch):
        """Пустая переменная считается незаданной.

        Иначе `DATA_PATH=` в compose дал бы путь `""`, то есть текущий
        каталог, и данные снова оказались бы рядом с исходниками.
        """
        monkeypatch.setenv("DATA_PATH", "")

        assert resolve_data_dir(None) == Path(DEFAULT_DATA_DIR)

    def test_resolved_at_call_time_not_import_time(self, monkeypatch: pytest.MonkeyPatch):
        """Переменная читается при вызове, а не фиксируется на импорте.

        Иначе подмена переменной в тесте не имела бы эффекта: значение уже
        было бы записано в константу на уровне модуля.
        """
        monkeypatch.delenv("DATA_PATH", raising=False)
        assert resolve_data_dir(None) == Path(DEFAULT_DATA_DIR)

        monkeypatch.setenv("DATA_PATH", "/srv/shp-data")
        assert resolve_data_dir(None) == Path("/srv/shp-data")


class TestStoragesReadEnvironment:
    """Каждое хранилище по умолчанию пишет в каталог из DATA_PATH."""

    @pytest.fixture(autouse=True)
    def _isolated_data_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Изолированный каталог данных на каждый тест."""
        target = tmp_path / "data"
        monkeypatch.setenv("DATA_PATH", str(target))
        self.data_dir = target

    def test_device_persistence(self):
        """DevicePersistence и два его хранилища."""
        from core.persistence.devices import (
            DeviceAccessPersistence,
            DevicePersistence,
            DeviceSyncEventPersistence,
        )

        for cls in (DevicePersistence, DeviceAccessPersistence, DeviceSyncEventPersistence):
            storage = cls()
            assert storage.data_dir == self.data_dir, (
                f"{cls.__name__} должен использовать DATA_PATH, а писал в {storage.data_dir}"
            )

    def test_source_persistence(self):
        """HASourcePersistence."""
        from core.persistence.sources import HASourcePersistence

        assert HASourcePersistence().data_dir == self.data_dir

    def test_persistence_manager_passes_path_to_components(self):
        """PersistenceManager и все его компоненты — один и тот же каталог."""
        from core.persistence.manager import PersistenceManager

        manager = PersistenceManager()

        assert manager.data_dir == self.data_dir
        assert manager.sources.data_dir == self.data_dir
        assert manager.devices.data_dir == self.data_dir

    def test_state_persistence_default_path(self):
        """Путь файла состояний по умолчанию."""
        from core.persistence.state_persistence import default_storage_path

        assert default_storage_path() == str(self.data_dir / "state.json")

    def test_event_store_db_path(self):
        """Журнал событий — SQLite внутри каталога данных."""
        from core.persistence.event_store import EventStore

        store = EventStore()

        assert store.db_path == self.data_dir / "history.db"
        assert store.db_path.exists()

    def test_migrations_runner(self):
        """Раннер миграций тоже должен работать внутри DATA_PATH."""
        from core.persistence.migrations.migrations_runner import MigrationsRunner

        assert MigrationsRunner().data_dir == self.data_dir

    def test_created_files_land_in_data_path(self):
        """Проверка на действии: файлы появляются там, где указано.

        Предыдущие тесты проверяли атрибуты. Этот создаёт хранилище и
        читает путь — то есть исполняет код, который в контейнере писал
        `/app/data` вместо тома.
        """
        from core.persistence.devices import DevicePersistence

        storage = DevicePersistence()
        assert storage.devices_file == self.data_dir / "devices.json"
        assert storage.devices_file.parent == self.data_dir


class TestNoHardcodedRelativeDefault:
    """Запрет на возврат литерала `"data"` как пути по умолчанию.

    Механическая проверка: именно этим способом вернулся бы дефект —
    достаточно добавить `data_dir: Path | str = "data"` в любой класс
    персистентности, и всё снова начнёт писаться относительно WORKDIR.
    """

    #: Классы персистентности, у которых путь по умолчанию обязан
    #: разрешаться через `resolve_data_dir`.
    PERSISTENCE_MODULES = (
        "core/persistence/devices.py",
        "core/persistence/sources.py",
        "core/persistence/manager.py",
        "core/persistence/event_store.py",
        "core/persistence/state_persistence.py",
        "core/persistence/migrations/migrations_runner.py",
        "core/persistence/migrations/db_init.py",
    )

    @pytest.mark.parametrize("relative_path", PERSISTENCE_MODULES)
    def test_module_has_no_hardcoded_data_default(self, relative_path: str):
        """В модулях персистентности не должно быть `= "data"` как дефолта."""
        import core

        root = Path(core.__file__).parent.parent
        source = (root / relative_path).read_text(encoding="utf-8")

        offenders = [
            line.strip()
            for line in source.splitlines()
            # Сигнатуры вида data_dir: Path | str = "data"
            if 'data_dir: Path | str = "data"' in line
            # И db_path: str = "data/history.db"
            or 'db_path: str = "data/' in line
        ]

        assert not offenders, (
            f"{relative_path}: путь по умолчанию снова зашит в исходник, "
            f"данные уйдут относительно WORKDIR, а не в DATA_PATH. "
            f"Найдено: {offenders}"
        )

    def test_paths_module_is_the_single_source(self):
        """Литерал `data` живёт только в `paths.py` как DEFAULT_DATA_DIR."""
        import core

        root = Path(core.__file__).parent.parent
        persistence_root = root / "core" / "persistence"

        offenders = []
        for path in sorted(persistence_root.rglob("*.py")):
            if path.name == "paths.py" or path.name == "examples.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                # `= "data"` в позиционном значении по умолчанию
                if '= "data"' in stripped and "DEFAULT_DATA_DIR" not in stripped:
                    offenders.append(f"{path.relative_to(root)}:{number}: {stripped}")

        assert not offenders, (
            "Литерал `data` должен быть только в paths.DEFAULT_DATA_DIR. "
            f"Найдено в других местах: {offenders}"
        )


class TestAppDoesNotPassExplicitPath:
    """Приложение не должно передавать путь явно.

    `app.py` создавал `PersistenceManager(data_dir="data")`. Явный аргумент
    перекрывает `DATA_PATH`, и это не дало эффекта, пока явно не убрали:
    `history.db` уезжал в том, а `sources.json` оставался в слое образа.
    """

    def test_app_passes_no_explicit_data_dir(self):
        """В `create_app` не должно быть `PersistenceManager(data_dir=...)`."""
        import core

        root = Path(core.__file__).parent.parent
        source = (root / "webui" / "app.py").read_text(encoding="utf-8")

        assert "PersistenceManager(data_dir=" not in source, (
            "create_app передаёт путь данных явно, из-за чего DATA_PATH "
            "игнорируется. Пусть PersistenceManager возьмёт его сам."
        )
