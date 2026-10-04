"""Запрет неразличимых допусков в проверках прав (спека 009, T028).

Допуск вида `assert response.status_code in [200, 404]` делает проверку прав
неотличимой от проверки несуществования: оба исхода означают «пользователь не
получил устройство», а проверить, **почему** он его не получил, такой ассерт
не позволяет. FR-022 требует конкретных ожиданий.

Тест не запрещает написание таких ассертов — он их находит. Список найденного
мест хранится в Known Issue #34: часть из них требует перевода на реальные
устройства, и это отдельная работа.

Проверка применяется не ко всем тестам, а к тем, что **о проверке прав**:
неразличимый допуск в HTTP-тесте интерфейса или команды — нормальная практика
там, где устройство заведомо может отсутствовать.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent.parent

#: Каталоги, где проверяется разграничение прав.
ACCESS_SCOPE = (
    ROOT / "tests" / "contract" / "test_access_control.py",
    ROOT / "tests" / "contract" / "test_device_access_rights.py",
    ROOT / "tests" / "integration" / "test_access_control.py",
)

#: Сочетания кодов, в которых «успех» и «отсутствует» неразличимы.
#: `404` означает «устройства нет», а `200`/`403` — результат проверки прав.
#: Значения — числа, как и элементы списка в ассерте. Строки здесь дали бы
#: сравнение множеств, которое никогда не срабатывает: `{"200"} <= {200}` ложно.
FORBIDDEN_PAIRS = [
    frozenset({200, 404}),
    frozenset({200, 202, 404}),
    frozenset({403, 404}),
    frozenset({200, 204, 404}),
]


def _intolerant_asserts(source: str) -> list[str]:
    """Находит ассерты, допускающие одновременно успех и 404.

    Разбор идёт по дереву синтаксиса, а не поиском подстроки: иначе проверка
    находила бы саму себя — собственный список запрещённых сочетаний.

    Args:
        source: Исходный код для разбора.

    Returns:
        Список найденных ассертов вида `assert ... in [...]`.
    """
    tree = ast.parse(source)
    found: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for inner in ast.walk(node.test):
            if not isinstance(inner, ast.Compare) or not isinstance(inner.ops[0], ast.In):
                continue
            comparator = inner.comparators[0]
            if not isinstance(comparator, ast.List):
                continue
            codes = {
                element.value
                for element in comparator.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, int)
            }
            if any(pair <= codes for pair in FORBIDDEN_PAIRS):
                found.append(ast.unparse(node))

    return found


@pytest.mark.parametrize("path", ACCESS_SCOPE, ids=lambda p: p.name)
def test_access_assertions_are_not_indistinguishable(path: Path):
    """Проверки прав не допускают одновременно успеха и отсутствия устройства.

    Args:
        path: Проверяемый файл.
    """
    offenders = _intolerant_asserts(path.read_text(encoding="utf-8"))

    assert not offenders, (
        f"{path.name}: проверка прав не должна допускать неразличимые исходы "
        f"(например 200 или 404) — это делает её неотличимой от проверки "
        f"несуществования. Найдено:\n  " + "\n  ".join(offenders)
    )


def test_known_offenders_are_listed_where_visible():
    """Известные места не спрятаны в ассертах — они перечислены в Known Issue.

    Проверка гарантирует, что список мест не пуст, пока правка не сделана: иначе
    запрет появился бы «на будущее» и скрыл бы текущее состояние.
    """
    state = ROOT / ".ai" / "01_PROJECT_STATE.md"
    text = state.read_text(encoding="utf-8")

    assert "test_access_control.py" in text, (
        "файлы с неразличимыми допусками должны быть названы в Known Issues"
    )
    assert re.search(r"неразличим|removed_from_ha|несуществующ", text, re.IGNORECASE), (
        "Known Issue должен описывать nature проблемы, а не только называть файл"
    )
