"""Сводка проблем дома для дашборда Home Assistant (B79).

На панели дома «проблемы» должны быть **читаемыми**: «Гостиная: Свет над столом —
автомат завис», а не «4». Поэтому здесь две вещи:

* сведение проблем из двух источников — обхода дома (молчащие датчики, батарейки,
  недоступные приборы) и сторожа автоматов (зависание, расхождение «модель ↔
  прибор», потеря связи);
* человеческая формулировка: место, имя прибора и причина.

Формулировки держатся рядом с данными, а не в шаблоне дашборда: владелец видит их
в состоянии сущности, в истории и в атрибутах, а не только в одной карточке.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

from core.models.health import ProblemLevel, level_for_kind


#: Зависание автомата: состояние держится дольше ожидаемого.
PROBLEM_FSM_STUCK = "fsm_stuck"

#: Расхождение «модель ↔ прибор», которое считается отказом (не уступкой человеку).
PROBLEM_DEVICE_MISMATCH = "device_mismatch"

#: Потеря связи с Home Assistant.
PROBLEM_HA_DISCONNECTED = "ha_disconnected"

#: Причина проблемы человеческим языком. Незнакомый вид называется собой: лучше
#: «house_unreadable», чем пустое место.
PROBLEM_REASONS: dict[str, str] = {
    "unavailable": "не отвечает",
    "stale": "молчит",
    "low_battery": "батарейка на исходе",
    "battery_silent": "батарейка молчит",
    "missing_entity": "нет в доме",
    "house_unreadable": "дом не прочитан",
    PROBLEM_FSM_STUCK: "автомат завис",
    PROBLEM_DEVICE_MISMATCH: "расхождение с прибором",
    PROBLEM_HA_DISCONNECTED: "нет связи с домом",
}

#: Предел длины состояния датчика: Home Assistant хранит состояние строкой и
#: обрезает слишком длинные значения в интерфейсе.
SUMMARY_LIMIT = 240

#: Технический префикс Zigbee-устройства в имени (`0xa4c138ef3971344e Батарея`):
#: владельцу он ничего не говорит, а место уже названо.
_HEX_PREFIX = re.compile(r"^0x[0-9a-fA-F]+\s+")

#: Причина в единственном и множественном числе: «Грядки: Батарея, Температура —
#: не отвечают» читается, а «не отвечает» про три датчика — нет.
_PLURALS: dict[str, str] = {
    "не отвечает": "не отвечают",
    "молчит": "молчат",
}


def clean_name(name: str) -> str:
    """Убрать из имени прибора технический префикс.

    Args:
        name: Имя из проблемы.

    Returns:
        Имя без `0x…`.
    """
    return _HEX_PREFIX.sub("", name).strip() or name


def watchdog_problems(
    snapshot: Any,
    *,
    device_names: dict[str, str] | None = None,
    areas: dict[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Проблемы автоматов из снимка сторожа.

    Args:
        snapshot: Снимок сторожа (``entries``, ``ha_disconnected``) либо None.
        device_names: Прибор → человеческое имя.
        areas: Прибор → (вид места, имя места).

    Returns:
        Список проблем в той же форме, что у обхода дома.
    """
    if snapshot is None:
        return []
    names = device_names or {}
    places = areas or {}
    problems: list[dict[str, Any]] = []

    if getattr(snapshot, "ha_disconnected", False):
        problems.append(
            {
                "kind": PROBLEM_HA_DISCONNECTED,
                "source": "автомат",
                "subject": "",
                "name": "Home Assistant",
                "area": "",
                "detail": "Нет связи с домом: команды и состояния не доходят",
            }
        )

    for entry in getattr(snapshot, "entries", ()) or ():
        device = str(getattr(entry, "device", "") or "")
        label = names.get(device) or device or str(getattr(entry, "entity_id", ""))
        where = (places.get(device) or ("", ""))[1]

        if getattr(entry, "stuck", False):
            limit = getattr(entry, "expected_timeout_sec", None)
            held = f"{limit / 60:.0f} мин" if limit else "дольше допустимого"
            problems.append(
                {
                    "kind": PROBLEM_FSM_STUCK,
                    "source": "автомат",
                    "subject": str(getattr(entry, "entity_id", "")),
                    "name": label,
                    "area": where,
                    "detail": (
                        f"{label} ({where or 'без места'}): состояние "
                        f"{getattr(entry, 'state', '?')} держится {held}"
                    ),
                }
            )

        if getattr(entry, "mismatch_is_fault", False):
            problems.append(
                {
                    "kind": PROBLEM_DEVICE_MISMATCH,
                    "source": "автомат",
                    "subject": device,
                    "name": label,
                    "area": where,
                    "detail": (
                        f"{label} ({where or 'без места'}): модель "
                        f"{getattr(entry, 'state', '?')}, прибор "
                        f"{getattr(entry, 'device_state', '?')} — "
                        f"{getattr(entry, 'mismatch_reason', '')}"
                    ),
                }
            )
    return problems


def levels_for(problems: list[dict[str, Any]] | None) -> dict[str, int]:
    """Число проблем по уровням важности.

    Args:
        problems: Плоский список проблем.

    Returns:
        Словарь ``info``/``warning``/``critical`` с числами.
    """
    levels = {level.value: 0 for level in ProblemLevel}
    for problem in problems or []:
        level = str(problem.get("level") or level_for_kind(str(problem.get("kind") or "")))
        levels[level] = levels.get(level, 0) + 1
    return levels


def compose_report(
    health_report: dict[str, Any] | None,
    snapshot: Any,
    *,
    device_names: dict[str, str] | None = None,
    areas: dict[str, tuple[str, str]] | None = None,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Свести проблемы дома и проблем автоматов в один снимок.

    Args:
        health_report: Последний снимок обхода дома либо None.
        snapshot: Последний снимок сторожа либо None.
        device_names: Прибор → человеческое имя.
        areas: Прибор → (вид места, имя места).
        registry: Реестр проблем; если задан, снимок попадает в историю.

    Returns:
        Снимок: ``generated_at``, ``sensor_count``, ``count``, ``levels`` и
        ``problems``.
    """
    health = health_report or {}
    problems = list(health.get("problems") or [])
    problems += watchdog_problems(snapshot, device_names=device_names, areas=areas)
    generated_at = health.get("generated_at") or getattr(snapshot, "taken_at", None)
    if registry is not None and generated_at:
        with contextlib.suppress(Exception):
            registry.observe_report(
                problems,
                str(generated_at),
                close_missing=bool(health.get("generated_at"))
                and bool(health.get("readable", True)),
            )
    return {
        "generated_at": generated_at,
        "sensor_count": health.get("sensor_count", 0),
        "count": len(problems),
        "levels": levels_for(problems),
        "problems": problems,
    }


def summary_text(problems: list[dict[str, Any]] | None) -> str:
    """Человеческая строка проблем для состояния датчика.

    Проблемы собираются по месту и причине: «Грядки: Батарея, Температура —
    не отвечают» вместо трёх повторов «Грядки: …». Так строка короче, а
    владелец видит картину, а не список.

    Args:
        problems: Список проблем.

    Returns:
        «Проблем нет» либо «4: Грядки: … — не отвечают; Улица: … — не отвечает».
    """
    items = list(problems or [])
    if not items:
        return "Проблем нет"

    grouped: dict[tuple[str, str], list[str]] = {}
    for problem in items:
        where = str(problem.get("area") or "").strip()
        reason = PROBLEM_REASONS.get(
            str(problem.get("kind") or ""), str(problem.get("kind") or "проблема")
        )
        name = clean_name(str(problem.get("name") or problem.get("subject") or "проблема"))
        grouped.setdefault((where, reason), []).append(name)

    parts: list[str] = []
    for (where, reason), names in grouped.items():
        unique = list(dict.fromkeys(names))
        label = ", ".join(unique)
        if len(unique) > 1:
            reason = _PLURALS.get(reason, reason)
        parts.append(f"{where}: {label} — {reason}" if where else f"{label} — {reason}")

    text = f"{len(items)}: " + "; ".join(parts)
    if len(text) > SUMMARY_LIMIT:
        text = text[: SUMMARY_LIMIT - 1].rstrip() + "…"
    return text
