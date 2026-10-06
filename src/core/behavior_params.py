"""Проверка параметров поведения в пяти слоях (пункт 4 веб-плана).

Слои именно в таком порядке, потому что каждый следующий имеет смысл только если
предыдущий пройден:

1. **Известность.** Параметр должен быть описан в контракте шаблона. Неизвестный
   параметр отвергается, а не игнорируется: иначе он молча пропадёт при
   перезаписи поведения, и пользователь увидит «сохранилось», хотя поле исчезло.
2. **Тип.** `int` не принимает `2.5`, `str` — число.
3. **Диапазон.** Число вне границ отвергается (`brightness` 0…255).
4. **Формат.** Строковые параметры проверяются по образцу (`ЧЧ:ММ-ЧЧ:ММ`).
5. **Связность и существование ссылки.** Значения должны быть согласованы между
   собой (окно расписания не нулевое) и ссылаться на существующее: поведение —
   на существующий шаблон из контракта.

Действенность параметра (`effective` в контракте) проверкой **не** запрещается:
инертный параметр принимается, иначе правка манифеста из редактора манифеста
перестала бы работать. Но он помечается в ответе — форма его не показывает как
работающий.

Пустое значение — это «взять значение по умолчанию», а не ошибка: так форма может
оставлять поле пустым, не зная значения по умолчанию.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


CONTRACT_PATH = Path(__file__).resolve().parent.parent / "features" / "CONTRACT.yaml"

_TIME_RANGE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


class ParamError(ValueError):
    """Ошибка проверки параметров поведения с указанием слоя."""


def load_contract() -> dict[str, Any]:
    """Загружает контракт шаблонов.

    Returns:
        Разобранный CONTRACT.yaml.
    """
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def template_params(contract: dict[str, Any], template: str) -> dict[str, Any] | None:
    """Возвращает описание параметров шаблона либо None, если шаблона нет.

    Args:
        contract: Контракт шаблонов.
        template: Имя шаблона.

    Returns:
        Описание параметров либо None.
    """
    entry = (contract.get("templates") or {}).get(template)
    return None if entry is None else (entry.get("params") or {})


def validate_behavior(template: str, params: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    """Проверяет параметры поведения по всем пяти слоям.

    Args:
        template: Имя шаблона поведения.
        params: Параметры из запроса.
        contract: Контракт шаблонов.

    Returns:
        Список замечаний об инертных параметрах (не ошибок).

    Raises:
        ParamError: С первым нарушением и его слоем в тексте.
    """
    declared = template_params(contract, template)
    if declared is None:
        raise ParamError(f"слой 5 (существование): шаблона «{template}» нет в контракте")

    for name, value in params.items():
        meta = declared.get(name)
        if meta is None:
            raise ParamError(
                f"слой 1 (известность): параметр «{name}» не описан в шаблоне "
                f"«{template}». Описанные: {sorted(declared) or '—'}. Параметр "
                f"был бы молча потерян при сохранении"
            )
        _check_type(name, value, meta)
        _check_range(name, value, meta)
        _check_format(name, value, meta)

    _check_consistency(template, params)

    return [name for name in params if not declared[name]["effective"]]


def _check_type(name: str, value: Any, meta: dict[str, Any]) -> None:
    """Проверяет слой 2 — тип значения.

    Args:
        name: Имя параметра.
        value: Значение.
        meta: Описание параметра.

    Raises:
        ParamError: При несовпадении типа.
    """
    expected = meta.get("type")
    if expected == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "float":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected == "str":
        ok = isinstance(value, str)
    else:
        raise ParamError(f"слой 2 (тип): для «{name}» не объявлен тип в контракте")
    if not ok:
        raise ParamError(
            f"слой 2 (тип): «{name}» ожидает {expected}, получено {type(value).__name__}"
        )


def _check_range(name: str, value: Any, meta: dict[str, Any]) -> None:
    """Проверяет слой 3 — числовой диапазон.

    Args:
        name: Имя параметра.
        value: Значение.
        meta: Описание параметра.

    Raises:
        ParamError: При выходе за границы.
    """
    spec = str(meta.get("range", ""))
    if "-" not in spec or not isinstance(value, (int, float)) or isinstance(value, bool):
        return
    low_text, high_text = spec.split("-", 1)
    try:
        low, high = float(low_text), float(high_text)
    except ValueError:
        return
    if not (low <= value <= high):
        raise ParamError(f"слой 3 (диапазон): «{name}»={value} вне {spec}")


def _check_format(name: str, value: Any, meta: dict[str, Any]) -> None:
    """Проверяет слой 4 — формат строкового значения.

    Args:
        name: Имя параметра.
        value: Значение.
        meta: Описание параметра.

    Raises:
        ParamError: При несовпадении образцу.
    """
    if not isinstance(value, str):
        return
    spec = str(meta.get("range", ""))
    if "-" not in spec or ":" not in spec:
        return
    if not _TIME_RANGE.match(value):
        raise ParamError(f"слой 4 (формат): «{name}»={value!r} ожидается ЧЧ:ММ-ЧЧ:ММ")


def _check_consistency(template: str, params: dict[str, Any]) -> None:
    """Проверяет слой 5 — согласованность значений между собой.

    Args:
        template: Имя шаблона.
        params: Параметры.

    Raises:
        ParamError: При противоречии.
    """
    window = params.get("schedule")
    if isinstance(window, str):
        match = _TIME_RANGE.match(window)
        if match:
            start = (int(match.group(1)), int(match.group(2)))
            end = (int(match.group(3)), int(match.group(4)))
            if start == end:
                raise ParamError(
                    f"слой 5 (связность): окно «{template}.schedule»={window} "
                    "нулевое — ночной режим не будет работать"
                )
