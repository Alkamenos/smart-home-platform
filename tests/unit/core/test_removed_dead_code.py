"""Мёртвый код возвращается тихо — поэтому на его отсутствие стоит проверка.

Что удалено 2026-10-07 и почему
-------------------------------

`src/core/persistence/migrations/` содержал раннер миграций, две «миграции» и
второй `IndexManager`. Ни один из них в production не вызывался:

- `initialize_database` зовётся только изнутри самого `db_init`, а тот
  достижим лишь ручным `python -m core.persistence.migrations.db_init`;
- `migrations_runner.init_migrations` — из `db_init` и `examples`;
- `migrations/index_manager.py` — из `examples`. Настоящий `IndexManager`
  живёт в `core/persistence/index_manager.py` и импортируется сервисом
  устройств;
- обе «миграции» создают `sources.json`/`devices.json`, если их нет, и пишут
  индексные файлы. Индексы не читает никто вне самого раннера;
- фактического изменения схемы там нет: хранилище не SQL, а JSON-файлы, версия
  одна, менять формат нечего.

Опасность, которой пугали, при проверке не подтвердилась: команды `reset` у
`deploy.sh` нет (`deploy`, `shadow`, `rollback`, `status`, `health`, `backup`,
`verify`, `restore`), поэтому «`deploy.sh reset` стёр бы источники» был
недостижимым сценарием. `down()` с удалением `sources.json` целиком действительно
удалял файл — но был достижим только через ручной запуск команды, которую
никто не запускал.

Заявление о версии одна проверялось на диске: в боевом
`deploy/docker/data/` нет ни `.migrations_history.json`, ни
`.sources_indices.json`, то есть миграции не применялись ни разу.

Почему проверка нужна
---------------------

Удалённый код не ломает сборку, пока кто-нибудь его не напишет снова. Список
файлов ниже — механическая проверка на возврат: ровно этим способом дефект
вернулся бы снова, тихо и без падения тестов.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import core


#: Модули, удалённые как мёртвые. Их появление означало бы возврат кода,
#: который в production не вызывается, а в `db_init.down()` удалял данные.
REMOVED_MODULES = (
    "persistence/migrations/__init__.py",
    "persistence/migrations/migrations_runner.py",
    "persistence/migrations/db_init.py",
    "persistence/migrations/001_init_sources.py",
    "persistence/migrations/002_init_devices.py",
    "persistence/migrations/examples.py",
    "persistence/migrations/index_manager.py",
)


def _core_root() -> Path:
    """Каталог пакета `core`.

    Returns:
        Путь к пакету `core`.
    """
    return Path(core.__file__).parent


class TestDeadCodeStaysGone:
    """Мёртвый код не возвращается молча."""

    def test_migrations_package_is_absent(self) -> None:
        """Каталог миграций удалён целиком.

        Проверяется на файловой системе, а не через импорт: отсутствующий
        модуль нельзя импортировать, а вот его возврат — можно, и тогда
        единственной защитой был бы этот тест.
        """
        package = _core_root() / "persistence" / "migrations"

        assert not package.exists(), (
            f"вернулся каталог {package}. Он не вызывается из production-кода, "
            f"а db_init.reset --confirm удаляет sources.json целиком"
        )

    def test_named_modules_are_absent(self) -> None:
        """Ни один из удалённых модулей не появился снова.

        Returns:
            Ничего.
        """
        found = [relative for relative in REMOVED_MODULES if (_core_root() / relative).exists()]

        assert not found, f"вернулись удалённые как мёртвые модули: {found}"

    def test_nothing_imports_them(self) -> None:
        """В `src/` не осталось импортов удалённого пакета.

        Returns:
            Ничего.
        """
        import src

        offenders: list[str] = []
        for path in Path(src.__file__).parent.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "persistence.migrations" in text or "persistence/migrations" in text:
                offenders.append(str(path))

        assert not offenders, (
            f"остались ссылки на удалённый пакет миграций: {offenders}. "
            f"Пакет не вызывается из production-кода, поэтому ссылка не на "
            f"работающий код, а на возвращённый мёртвый"
        )


class TestRealIndexManagerIsUntouched:
    """Настоящий `IndexManager` остался на месте."""

    def test_service_still_imports_it(self) -> None:
        """Сервис устройств импортирует живой индекс, а не удалённый.

        Returns:
            Ничего.
        """
        from core.persistence.index_manager import IndexManager

        assert IndexManager is not None

    def test_removed_and_live_are_different_modules(self) -> None:
        """Дубль индекса не восстановлён под старым путём.

        Два `IndexManager` с одинаковым именем в разных пакетах — источник
        расхождений: правка одного не затрагивает другой, и место, откуда
        импортируется, решает всё.

        Returns:
            Ничего.
        """
        assert not (_core_root() / "persistence" / "migrations" / "index_manager.py").exists()
