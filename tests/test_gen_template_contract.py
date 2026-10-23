"""Генератор контракта умеет проверять, а не только перезаписывать (К-14).

Контракт шаблонов (`src/features/CONTRACT.yaml`) собран из кода, но два раздела —
`gaps` и `params` — пишутся руками. Прямой запуск генератора перезаписывает файл,
поэтому проверку «контракт не устарел» нельзя делать записью: она затрёт ручные
правки. Для этого добавлен режим `--check`: он ничего не пишет и возвращает 1,
если файл разошёлся с кодом.

Проверки держат обе стороны: актуальный контракт проходит, испорченный — нет.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


#: Корень репозитория: генератор читает `src/features` относительно него.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Файл контракта.
CONTRACT = REPO_ROOT / "src" / "features" / "CONTRACT.yaml"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Запустить генератор контракта.

    Args:
        *args: Аргументы генератора.

    Returns:
        Результат запуска.
    """
    # Кодировка задана явно с обеих сторон: на Windows локаль — cp1251, а
    # генератор печатает по-русски. Без этого проверка падала на mojibake
    # («контракт совпадает» превращалось в «РєРѕРЅС‚СЂР°РєС‚...»), хотя
    # контракт был в порядке.
    return subprocess.run(
        [sys.executable, "tools/gen_template_contract.py", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=120,
    )


class TestContractCheckMode:
    """`--check` не пишет файл и честно называет расхождение."""

    def test_current_contract_passes(self) -> None:
        """Актуальный контракт совпадает с кодом."""
        result = _run("--check")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "совпадает" in result.stdout

    def test_stale_contract_is_detected_without_writing(self, tmp_path: Path) -> None:
        """Испорченный контракт назван устаревшим, а файл не перезаписан."""
        stale = tmp_path / "CONTRACT.yaml"
        stale.write_text(
            CONTRACT.read_text(encoding="utf-8").replace("reachable: true", "reachable: false", 1),
            encoding="utf-8",
        )
        before = stale.read_text(encoding="utf-8")

        result = _run("--check", str(stale))

        assert result.returncode == 1
        assert "устарел" in result.stdout
        assert stale.read_text(encoding="utf-8") == before, "проверка переписала файл"
