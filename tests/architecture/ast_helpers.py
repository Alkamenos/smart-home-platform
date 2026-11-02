"""Помощники для архитектурных проверок: AST, импорты, размеры.

Модуль намеренно не зависит от pytest: те же функции использует
`tools/dead_code_inventory.py`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


#: Корень репозитория (файл лежит в tests/architecture/).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Корень исходников.
SRC_ROOT = PROJECT_ROOT / "src"


def python_files(root: Path = SRC_ROOT) -> list[Path]:
    """Перечислить Python-модули под каталогом.

    Args:
        root: Каталог поиска; по умолчанию `src`.

    Returns:
        Отсортированный список путей.
    """
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def relative_path(path: Path) -> str:
    """Путь относительно корня репозитория в POSIX-виде.

    Args:
        path: Абсолютный или относительный путь.

    Returns:
        Строка вида `src/core/fsm/engine.py`.
    """
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def module_name(path: Path) -> str:
    """Имя модуля так, как его пишут в импорте.

    Args:
        path: Путь к файлу.

    Returns:
        `core.fsm.engine`, `webui.models` и т. п.
    """
    relative = path.resolve().relative_to(SRC_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(path: Path) -> set[str]:
    """Собрать имена модулей, импортируемых файлом.

    Относительные импорты возвращаются с ведущими точками: для проверки
    направления зависимостей между пакетами они не нужны, но полезны в отчёте.

    Args:
        path: Путь к Python-файлу.

    Returns:
        Множество имён модулей.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix = "." * node.level
                modules.add(prefix + (node.module or ""))
            elif node.module:
                modules.add(node.module)
    return modules


def top_level_names(path: Path) -> tuple[set[str], set[str]]:
    """Собрать имена классов и функций верхнего уровня.

    Args:
        path: Путь к Python-файлу.

    Returns:
        Пара `(классы, функции)`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes: set[str] = set()
    functions: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
    return classes, functions


def line_count(path: Path) -> int:
    """Число строк в файле.

    Args:
        path: Путь к файлу.

    Returns:
        Количество строк.
    """
    return len(path.read_text(encoding="utf-8").splitlines())


def iter_imports_by_area() -> Iterator[tuple[str, str, str]]:
    """Перечислить импорты «пакет → пакет» для матрицы зависимостей.

    Yields:
        Пары `(исходный пакет, целевой пакет, файл)`.
    """
    areas = {"core", "adapters", "services", "webui", "dashboard", "smart_home", "cli", "app"}
    for path in python_files():
        source = module_name(path).split(".", 1)[0]
        if source not in areas:
            continue
        for target_module in imported_modules(path):
            target = target_module.lstrip(".").split(".", 1)[0]
            if target in areas:
                yield source, target, relative_path(path)
