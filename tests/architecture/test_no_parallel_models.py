"""Параллельные доменные модели запрещены (спека 018, US1/US4).

Одно понятие — одно определение. DTO на границе допустимы, вторая модель
манифеста — нет: именно так расходились сохранение и исполнение.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import ast

from tests.architecture.allowlist import PARALLEL_MODEL_ALLOWLIST
from tests.architecture.ast_helpers import python_files, relative_path


MANIFEST_CLASSES = frozenset(
    {
        "ManifestModel",
        "InstanceConfig",
        "RoomConfig",
        "DeviceConfig",
        "BehaviorConfig",
        "AutomationRules",
        "DashboardConfig",
    }
)

CANONICAL = "src/core/models/manifest.py"


def test_manifest_classes_are_defined_only_in_canonical_model() -> None:
    """Классы описания дома объявлены только в канонической модели."""
    duplicates: list[str] = []
    for path in python_files():
        relative = relative_path(path)
        if relative == CANONICAL:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in MANIFEST_CLASSES:
                key = f"{relative}:{node.name}"
                if key in PARALLEL_MODEL_ALLOWLIST:
                    continue
                duplicates.append(key)

    assert not duplicates, "параллельные определения описания дома: " + ", ".join(duplicates)
