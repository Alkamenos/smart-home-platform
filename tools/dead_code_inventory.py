"""Inventory Python modules that are not imported anywhere (spec 018, T074).

The tool is deliberately simple: it looks for the module stem in import lines
across ``src`` and ``tests``. Dynamic imports and entry points are excluded.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"

SKIP_NAMES = {"__init__.py", "main.py", "conftest.py", "setup.py"}
SKIP_DIRS = {"__pycache__", ".venv"}


def _python_files(root: Path) -> list[Path]:
    return [
        path for path in root.rglob("*.py") if not any(part in SKIP_DIRS for part in path.parts)
    ]


def _imported_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[-1])
            for alias in node.names:
                names.add(alias.name)
    return names


def inventory() -> list[tuple[Path, int]]:
    """Return modules whose stem is never imported outside themselves."""
    imports: dict[Path, set[str]] = {}
    for path in _python_files(SRC) + _python_files(TESTS):
        imports[path] = _imported_names(path)

    candidates: list[tuple[Path, int]] = []
    for path in _python_files(SRC):
        if path.name in SKIP_NAMES:
            continue
        stem = path.stem
        if stem.startswith("_"):
            continue
        references = sum(1 for other, names in imports.items() if other != path and stem in names)
        if references == 0:
            candidates.append((path.relative_to(ROOT), references))
    return sorted(candidates)


def main() -> int:
    """Print the inventory as Markdown rows."""
    print("| Файл | Импортов |")
    print("|---|---:|")
    for path, count in inventory():
        print(f"| `{path.as_posix()}` | {count} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
