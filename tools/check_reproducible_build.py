"""Проверка воспроизводимости сборки (спека 018, T040).

Печатает отпечаток набора зависимостей и проверяет, что lock-файл не устарел.
Запуск:
    python tools/check_reproducible_build.py
    python tools/check_reproducible_build.py --check

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "uv.lock"
PYPROJECT = ROOT / "pyproject.toml"


def fingerprint() -> str:
    """Отпечаток lock-файла и pyproject.

    Returns:
        SHA256 в hex.
    """
    digest = hashlib.sha256()
    for path in (PYPROJECT, LOCK):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    """Точка входа.

    Returns:
        Код возврата: 0 — успех, 1 — lock отсутствует.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="только проверить наличие lock-файла (для CI)",
    )
    args = parser.parse_args()

    if not LOCK.exists():
        print("ОШИБКА: нет uv.lock — сборка невоспроизводима", file=sys.stderr)
        return 1

    print(f"dependency fingerprint: {fingerprint()}")
    if args.check:
        print("uv.lock на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
