"""Зависимости зафиксированы, сборка не разрешает версии на лету (US3).

Без lock-файла «собрано из этого коммита» означает разные системы в разные дни.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "uv.lock"
PYPROJECT = ROOT / "pyproject.toml"
DOCKERFILE = ROOT / "deploy" / "docker" / "Dockerfile"


def test_lockfile_exists_and_matches_project() -> None:
    """Lock-файл есть и описывает этот проект."""
    assert LOCK.exists(), "нет uv.lock: версии зависимостей не зафиксированы"

    data = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert data.get("version") == 1
    packages = {item["name"] for item in data.get("package", [])}
    assert project["name"] in packages, f"проекта {project['name']} нет в lock-файле"


def test_dockerfile_uses_frozen_install() -> None:
    """Сборка образа не разрешает зависимости заново."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "uv sync --frozen" in dockerfile or "uv pip install --require-hashes" in dockerfile, (
        "Dockerfile не использует зафиксированный набор зависимостей"
    )
    assert "uv.lock" in dockerfile, "lock-файл не копируется в сборку"


def test_dependency_specs_have_upper_bounds_or_lock() -> None:
    """Открытые диапазоны допустимы только при наличии lock-файла."""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    open_ranges = [
        dep for dep in project["dependencies"] if ">=" in dep and "<" not in dep and "==" not in dep
    ]

    assert LOCK.exists() or not open_ranges, (
        f"зависимости без верхней границы и без lock-файла: {open_ranges}"
    )
