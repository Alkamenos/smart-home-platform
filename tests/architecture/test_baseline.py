"""Baseline архитектурных проверок (спека 018, T010).

Тест не проверяет бизнес-логику: он напоминает, что архитектурные правила
входят в общий прогон, а allowlist не ссылается на несуществующие файлы.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from tests.architecture.allowlist import (
    IMPORT_ALLOWLIST,
    LEGACY_SIZE_ALLOWLIST,
    PARALLEL_MODEL_ALLOWLIST,
)
from tests.architecture.ast_helpers import PROJECT_ROOT, line_count


def test_architecture_suite_has_tests() -> None:
    """Каталог архитектурных проверок не пуст."""
    files = list((PROJECT_ROOT / "tests" / "architecture").glob("test_*.py"))

    assert files, "tests/architecture пуст: правила не проверяются"


def test_size_allowlist_points_to_existing_files_and_is_current() -> None:
    """Allowlist не врёт о размерах и не ссылается на удалённые файлы."""
    for relative, limit in LEGACY_SIZE_ALLOWLIST.items():
        path = PROJECT_ROOT / relative
        assert path.exists(), f"allowlist ссылается на несуществующий файл: {relative}"
        assert line_count(path) <= limit, (
            f"{relative} вырос до {line_count(path)} строк при пределе {limit}: "
            "обновите allowlist осознанно или уменьшите модуль"
        )


def test_import_allowlist_points_to_existing_files() -> None:
    """Временные исключения импортов указывают на реальные файлы."""
    for files in IMPORT_ALLOWLIST.values():
        for relative in files:
            assert (PROJECT_ROOT / relative).exists(), (
                f"исключение импорта ссылается на несуществующий файл: {relative}"
            )


def test_parallel_model_allowlist_is_honest() -> None:
    """Временные дубли моделей существуют и имеют причину."""
    for key, reason in PARALLEL_MODEL_ALLOWLIST.items():
        relative, _, class_name = key.partition(":")
        assert (PROJECT_ROOT / relative).exists(), (
            f"исключение параллельной модели ссылается на несуществующий файл: {relative}"
        )
        assert reason.strip(), f"у исключения {key} нет причины"
        assert class_name, f"у исключения {key} не назван класс"


def test_no_absolute_paths_in_allowlist() -> None:
    """Allowlist использует пути от корня, а не абсолютные."""
    for relative in LEGACY_SIZE_ALLOWLIST:
        assert not Path(relative).is_absolute(), f"абсолютный путь в allowlist: {relative}"
