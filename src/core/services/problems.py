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

from typing import Any


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
    "missing_entity": "нет в доме",
    "house_unreadable": "дом не прочитан",
    PROBLEM_FSM_STUCK: "автомат завис",
    PROBLEM_DEVICE_MISMATCH: "расхождение с прибором",
    PROBLEM_HA_DISCONNECTED: "нет связи с домом",
}

#: Предел длины состояния датчика: Home Assistant хранит состояние строкой и
#: обрезает слишком длинные значения в интерфейсе.
SUMMARY_LIMIT = 240


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


def compose_report(
    health_report: dict[str, Any] | None,
    snapshot: Any,
    *,
    device_names: dict[str, str] | None = None,
    areas: dict[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Свести проблемы дома и проблем автоматов в один снимок.

    Args:
        health_report: Последний снимок обхода дома либо None.
        snapshot: Последний снимок сторожа либо None.
        device_names: Прибор → человеческое имя.
        areas: Прибор → (вид места, имя места).

    Returns:
        Снимок: ``generated_at``, ``sensor_count``, ``count`` и ``problems``.
    """
    health = health_report or {}
    problems = list(health.get("problems") or [])
    problems += watchdog_problems(snapshot, device_names=device_names, areas=areas)
    return {
        "generated_at": health.get("generated_at") or getattr(snapshot, "taken_at", None),
        "sensor_count": health.get("sensor_count", 0),
        "count": len(problems),
        "problems": problems,
    }


def summary_text(problems: list[dict[str, Any]] | None) -> str:
    """Человеческая строка проблем для состояния датчика.

    Args:
        problems: Список проблем.

    Returns:
        «Проблем нет» либо «3: Гостиная: Свет — автомат завис; …».
    """
    items = list(problems or [])
    if not items:
        return "Проблем нет"

    parts: list[str] = []
    for problem in items:
        name = str(problem.get("name") or problem.get("subject") or "проблема")
        where = str(problem.get("area") or "")
        reason = PROBLEM_REASONS.get(
            str(problem.get("kind") or ""), str(problem.get("kind") or "проблема")
        )
        label = f"{where}: {name}" if where else name
        parts.append(f"{label} — {reason}")

    text = f"{len(items)}: " + "; ".join(parts)
    if len(text) > SUMMARY_LIMIT:
        text = text[: SUMMARY_LIMIT - 1].rstrip() + "…"
    return text
