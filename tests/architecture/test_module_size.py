"""Бюджет размера модулей (спека 018, US4).

Новый модуль не должен сразу становиться god-файлом; существующие крупные
модули фиксируются в allowlist и сокращаются по плану.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from tests.architecture.allowlist import LEGACY_SIZE_ALLOWLIST, SIZE_BUDGET
from tests.architecture.ast_helpers import line_count, python_files, relative_path


def test_modules_fit_size_budget() -> None:
    """Все модули укладываются в бюджет или в исключение."""
    oversized: list[str] = []
    for path in python_files():
        relative = relative_path(path)
        limit = LEGACY_SIZE_ALLOWLIST.get(relative, SIZE_BUDGET)
        size = line_count(path)
        if size > limit:
            oversized.append(f"{relative}: {size} > {limit}")

    assert not oversized, (
        "модули выросли сверх бюджета: " + ", ".join(oversized) + ". "
        "Разделите ответственность или обновите allowlist осознанно."
    )
