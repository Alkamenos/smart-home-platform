"""Инвентаризация мёртвого кода (спека 018, T004).

Инструмент не «доказывает» мёртвость: он показывает кандидатов — модули,
классы и функции, на которые нет ссылок вне определяющего файла. Динамические
реестры (guard/action по строковому имени) учитываются: в корпус ссылок
включаются YAML-шаблоны и контракт.

Запуск:
    python tools/dead_code_inventory.py
    python tools/dead_code_inventory.py --json

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _python_files(root: Path = SRC) -> list[Path]:
    """Перечислить Python-модули.

    Args:
        root: Каталог поиска.

    Returns:
        Отсортированный список путей.
    """
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _reference_corpus() -> str:
    """Собрать текст, в котором ищутся ссылки.

    Returns:
        Код `src` и YAML-шаблоны/контракт: имена guard и action живут там.
    """
    chunks: list[str] = []
    for path in _python_files():
        chunks.append(path.read_text(encoding="utf-8"))
    features = ROOT / "src" / "features"
    if features.is_dir():
        for path in features.glob("*.yaml"):
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _top_level_names(path: Path) -> tuple[set[str], set[str]]:
    """Классы и функции верхнего уровня.

    Args:
        path: Python-файл.

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


def _count_references(name: str, corpus: str, own_text: str) -> int:
    """Сколько раз имя встречается вне определяющего файла.

    Args:
        name: Имя класса/функции.
        corpus: Полный корпус текста.
        own_text: Текст определяющего файла.

    Returns:
        Число вхождений в других файлах (приблизительно).
    """
    total = len(re.findall(rf"\b{re.escape(name)}\b", corpus))
    own = len(re.findall(rf"\b{re.escape(name)}\b", own_text))
    return max(total - own, 0)


def inventory() -> dict[str, list[str]]:
    """Собрать кандидатов в мёртвый код.

    Returns:
        Словарём с ключами `classes`, `functions`, `modules`.
    """
    corpus = _reference_corpus()
    classes: list[str] = []
    functions: list[str] = []
    modules: list[str] = []

    module_names: set[str] = set()
    for path in _python_files():
        relative = path.relative_to(SRC).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        module_names.add(".".join(parts))

    for path in _python_files():
        own_text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        path_classes, path_functions = _top_level_names(path)
        for name in sorted(path_classes):
            if _count_references(name, corpus, own_text) == 0:
                classes.append(f"{relative}:{name}")
        for name in sorted(path_functions):
            if _count_references(name, corpus, own_text) == 0:
                functions.append(f"{relative}:{name}")

    imported: set[str] = set()
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    for name in sorted(module_names):
        if name not in imported and not _module_imported_by_prefix(name, imported):
            modules.append(name)

    return {"classes": classes, "functions": functions, "modules": modules}


def _module_imported_by_prefix(name: str, imported: set[str]) -> bool:
    """Импортируется ли модуль как часть пакета.

    Args:
        name: Имя модуля.
        imported: Все импортированные имена.

    Returns:
        True, если импортируется сам модуль или его подмодуль.
    """
    return any(item == name or item.startswith(name + ".") for item in imported)


def main() -> int:
    """Точка входа.

    Returns:
        Код возврата.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="вывести JSON")
    args = parser.parse_args()

    report = inventory()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("Кандидаты в мёртвый код (без ссылок вне определяющего файла):")
    for title, key in (
        ("Классы", "classes"),
        ("Функции", "functions"),
        ("Модули без импорта", "modules"),
    ):
        print(f"\n## {title}")
        if not report[key]:
            print("  — нет")
        for item in report[key]:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
