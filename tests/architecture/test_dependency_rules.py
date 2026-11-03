"""Направление зависимостей: ядро не знает про инфраструктуру (спека 018, US4).

Конституция IV: Core не зависит от Adapters. Правило проверяется AST-разбором,
а не договорённостью: нарушение ломает тест.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from tests.architecture.allowlist import IMPORT_ALLOWLIST
from tests.architecture.ast_helpers import (
    SRC_ROOT,
    imported_modules,
    module_name,
    python_files,
    relative_path,
)


FORBIDDEN_FOR_CORE = ("adapters", "webui", "services", "dashboard", "app")
FORBIDDEN_FOR_ADAPTERS = ("webui", "services")


def _area(path: Path) -> str:
    """Первый сегмент имени модуля.

    Args:
        path: Python-файл.

    Returns:
        Имя пакета.
    """
    return module_name(path).split(".", 1)[0]


def test_core_does_not_import_infrastructure() -> None:
    """`core` не импортирует адаптеры, WebUI, прикладные сервисы или app."""
    violations: list[str] = []
    for path in python_files(SRC_ROOT / "core"):
        relative = relative_path(path)
        allowed = IMPORT_ALLOWLIST.get(("core", "adapters"), {})
        for target in imported_modules(path):
            area = target.lstrip(".").split(".", 1)[0]
            if area in FORBIDDEN_FOR_CORE and relative not in allowed:
                violations.append(f"{relative}: {target}")

    assert not violations, (
        "ядро зависит от инфраструктуры: " + ", ".join(violations) + ". "
        "Composition root должен жить в src/app/"
    )


def test_adapters_do_not_import_webui_or_services() -> None:
    """Адаптеры не тянут WebUI и прикладные сервисы."""
    violations: list[str] = []
    for path in python_files(SRC_ROOT / "adapters"):
        for target in imported_modules(path):
            area = target.lstrip(".").split(".", 1)[0]
            if area in FORBIDDEN_FOR_ADAPTERS:
                violations.append(f"{relative_path(path)}: {target}")

    assert not violations, "адаптеры зависят от верхних слоёв: " + ", ".join(violations)


def test_webui_does_not_import_adapters_directly() -> None:
    """WebUI общается с домом через сервисы, а не с HA-адаптером напрямую."""
    allowed = IMPORT_ALLOWLIST.get(("webui", "adapters"), {})
    violations: list[str] = []
    for path in python_files(SRC_ROOT / "webui"):
        relative = relative_path(path)
        if relative in allowed:
            continue
        for target in imported_modules(path):
            if target.startswith("adapters"):
                violations.append(f"{relative}: {target}")

    assert not violations, "WebUI импортирует адаптер напрямую: " + ", ".join(violations)
