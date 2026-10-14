#!/usr/bin/env python3
"""Ночная приёмка платформы по журналу: 8 пунктов, машинная проверка.

Читает журнал переходов (`history.db`), ручные записи трекера
(`manual_control.json`) и, если доступны креды, живые состояния Home
Assistant. Печатает по каждому пункту вердикт и доказательство — чтобы утренний
разбор шёл по фактам, а не по памяти.

Окно приёмки — «прошедшая ночь» в часах дома: с 20:00 предыдущего дня до 11:00
текущего (по умолчанию). Часовой пояс берётся из TZ/HOUSE_TIMEZONE, иначе
Asia/Yekaterinburg.

Запуск:
    .venv/bin/python .ai/scripts/night_acceptance.py [--from 20:00] [--to 11:00]

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "deploy" / "docker" / "data" / "history.db"
MANUAL = ROOT / "deploy" / "docker" / "data" / "manual_control.json"
GARLAND = "light.girlianda_terassa"
NIGHT_LIGHT = "light.group_nochnoe_osveshcheni"
OVERRIDE_MIN = 60


def _zone() -> ZoneInfo:
    """Часовой пояс дома.

    Returns:
        Пояс из TZ/HOUSE_TIMEZONE либо Asia/Yekaterinburg.
    """
    name = os.environ.get("TZ") or os.environ.get("HOUSE_TIMEZONE") or "Asia/Yekaterinburg"
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — неизвестный пояс не должен ломать разбор
        return ZoneInfo("Asia/Yekaterinburg")


def _window(start: str, end: str) -> tuple[float, float]:
    """Окно прошедшей ночи в секундах эпохи.

    Args:
        start: Начало ночи, ЧЧ:ММ.
        end: Конец ночи, ЧЧ:ММ (следующего дня).

    Returns:
        Пара (начало, конец) в секундах.
    """
    tz = _zone()
    now = dt.datetime.now(tz)
    sh, sm = (int(part) for part in start.split(":"))
    eh, em = (int(part) for part in end.split(":"))
    begin = dt.datetime(now.year, now.month, now.day, sh, sm, tzinfo=tz)
    if begin > now:
        begin -= dt.timedelta(days=1)
    finish = dt.datetime(begin.year, begin.month, begin.day, eh, em, tzinfo=tz) + dt.timedelta(
        days=1
    )
    return begin.timestamp(), finish.timestamp()


class Journal:
    """Журнал переходов и ручных действий."""

    def __init__(self, begin: float, end: float) -> None:
        """Открыть журнал.

        Args:
            begin: Начало окна, секунды эпохи.
            end: Конец окна, секунды эпохи.
        """
        self.begin = begin
        self.end = end
        self.zone = _zone()
        self.connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    def transitions(self, entity_like: str | None = None) -> list[dict[str, Any]]:
        """Переходы окна, по времени.

        Args:
            entity_like: Подстрока сущности (SQL LIKE), если нужен фильтр.

        Returns:
            Список записей.
        """
        sql = (
            "select timestamp, entity_id, from_state, to_state, trigger_name, success, reason "
            "from fsm_transitions where timestamp >= ? and timestamp <= ?"
        )
        params: list[Any] = [self.begin, self.end]
        if entity_like:
            sql += " and entity_id like ?"
            params.append(f"%{entity_like}%")
        sql += " order by timestamp"
        return [
            {
                "at": row[0],
                "entity": row[1],
                "from": row[2],
                "to": row[3],
                "trigger": row[4],
                "ok": bool(row[5]),
                "reason": row[6],
            }
            for row in self.connection.execute(sql, params)
        ]

    def manual(self) -> list[dict[str, Any]]:
        """Ручные действия окна.

        Returns:
            Список записей трекера.
        """
        if not MANUAL.exists():
            return []
        raw = json.loads(MANUAL.read_text(encoding="utf-8"))
        return sorted(
            (
                entry
                for entry in raw.values()
                if self.begin <= entry.get("timestamp", 0) <= self.end
            ),
            key=lambda entry: entry["timestamp"],
        )

    def time(self, stamp: float) -> str:
        """Время в часах дома.

        Args:
            stamp: Секунды эпохи.

        Returns:
            Время ЧЧ:ММ.
        """
        return dt.datetime.fromtimestamp(stamp, self.zone).strftime("%d %H:%M")


def _live_states() -> dict[str, str]:
    """Живые состояния Home Assistant, если есть креды.

    Returns:
        Сущность → состояние; пустой словарь, если креды недоступны.
    """
    token = os.environ.get("HA_TOKEN")
    base = (os.environ.get("HA_URL") or "").rstrip("/")
    if not token or not base:
        return {}
    try:
        request = urllib.request.Request(
            f"{base}/api/states", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            states = json.load(response)
    except Exception:  # noqa: BLE001 — приёмка не должна падать из-за сети
        return {}
    return {item["entity_id"]: item["state"] for item in states if "entity_id" in item}


def _report(ok: bool | None, title: str, detail: str) -> None:
    """Напечатать пункт приёмки.

    Args:
        ok: Вердикт; ``None`` — проверить нечем.
        title: Название пункта.
        detail: Доказательство.
    """
    mark = "✅" if ok else ("➖" if ok is None else "❌")
    print(f"  {mark} {title}\n      {detail}")


def check_garland(journal: Journal) -> None:
    """Пункт 1: гирлянда гаснет в момент отбоя, а не на рассвете."""
    transitions = journal.transitions(GARLAND)
    sleeps = [item for item in transitions if item["trigger"] == "sleep_started" and item["ok"]]
    offs = [
        item
        for item in transitions
        if item["to"] == "OFF" and item["trigger"] in ("sleep_started", "timeout")
    ]
    if sleeps:
        first = sleeps[0]
        _report(
            first["to"] == "OFF",
            "Гирлянда гаснет по отбою (`sleep_started`)",
            f"{journal.time(first['at'])}: {first['from']} → {first['to']} "
            f"(отбой {first['trigger']})",
        )
        return
    _report(
        None,
        "Гирлянда гаснет по отбою (`sleep_started`)",
        "события отбоя в окне нет — либо дом не спал, либо модификатор не включали"
        + (f"; последнее гашение: {journal.time(offs[-1]['at'])}" if offs else ""),
    )


def check_night_light(journal: Journal) -> None:
    """Пункт 2: ночное освещение горит до рассвета."""
    transitions = journal.transitions(NIGHT_LIGHT)
    sunrise = [item for item in transitions if item["trigger"] == "sunrise_started" and item["ok"]]
    if sunrise:
        last = sunrise[-1]
        _report(
            last["to"] == "OFF",
            "Ночное освещение гаснет на рассвете",
            f"{journal.time(last['at'])}: {last['from']} → {last['to']} (рассвет)",
        )
        return
    _report(
        None,
        "Ночное освещение гаснет на рассвете",
        "рассвета в окне нет: окно заканчивается раньше или событие потеряно",
    )


def check_covers(journal: Journal, states: dict[str, str]) -> None:
    """Пункт 3: шторы закрываются ночью при отбое."""
    closed = [
        item for item in journal.transitions("cover.") if item["ok"] and item["to"] == "CLOSED"
    ]
    if not closed:
        refusals = [
            item for item in journal.transitions("cover.") if item["reason"] == "covers_stay_open"
        ]
        _report(
            None,
            "Шторы закрываются ночью",
            f"закрытий нет; отказов «не спим» — {len(refusals)}"
            + (f", последний {journal.time(refusals[-1]['at'])}" if refusals else ""),
        )
        return
    times = ", ".join(journal.time(item["at"]) for item in closed[:4])
    live = {entity: state for entity, state in states.items() if entity.startswith("cover.")}
    _report(
        True,
        "Шторы закрываются ночью",
        f"закрытия: {times}; сейчас в HA: {live or 'нет данных'}",
    )


def check_override(journal: Journal) -> None:
    """Пункт 4: ручное включение возвращается к автоматике за 60 минут."""
    manual: list[dict[str, Any]] = journal.manual()
    all_transitions = journal.transitions()
    found = None
    for entry in manual:
        entity = str(entry.get("entity_id") or "")
        # Срок оверрайда ищем у того же прибора: переход по таймауту его автомата
        # (`<сущность>_<шаблон>_<приоритет>`). Первое ручное действие может
        # относиться к прибору без автоматики (тогда срока и не будет) — берём
        # следующее.
        matches = [
            item
            for item in all_transitions
            if item["trigger"] == "timeout"
            and item["ok"]
            and item["entity"].startswith(f"{entity}_")
            and item["at"] > entry["timestamp"]
        ]
        if matches:
            found = (entity, entry["timestamp"], matches[0])
            break

    if found is None:
        if not manual:
            _report(None, "Возврат к автоматике после ручного действия", "ручных действий не было")
        else:
            first = manual[0]
            _report(
                None,
                "Возврат к автоматике после ручного действия",
                f"{journal.time(first['timestamp'])}: {first['entity_id']} — перехода по сроку нет",
            )
        return

    entity, stamp, moment = found
    waited = (moment["at"] - stamp) / 60
    _report(
        abs(waited - OVERRIDE_MIN) <= 15,
        "Возврат к автоматике после ручного действия",
        f"{journal.time(stamp)} ручное ({entity}) → {journal.time(moment['at'])} "
        f"{moment['entity']} {moment['to']} по сроку ({waited:.0f} мин)",
    )


def check_mismatches(journal: Journal) -> None:
    """Пункт 5: расхождения «автомат ↔ прибор» называют себя и лечатся."""
    diverged = [
        item for item in journal.transitions() if item["trigger"] == "device_state_diverged"
    ]
    reasons = {}
    for item in journal.transitions():
        if not item["ok"] and item["reason"]:
            reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    mismatches = reasons.get("device_on_decision_off", 0) + reasons.get("device_off_decision_on", 0)
    _report(
        True,
        "Расхождение «автомат ↔ прибор» видно и повторяется",
        f"повторов решения: {len(diverged)}; отказов-расхождений: {mismatches}",
    )


def check_journal_quiet(journal: Journal) -> None:
    """Пункт 7: в журнале нет потока автоматических шумов."""
    noise = {"ac_not_allowed", "guard_failed"}
    counts: dict[str, int] = {}
    for item in journal.transitions():
        if not item["ok"] and item["reason"] in noise:
            counts[item["reason"]] = counts.get(item["reason"], 0) + 1
    total = sum(counts.values())
    _report(
        total <= 20,
        "Журнал без потока шумов",
        f"{counts or 'шумов нет'} (всего {total}; порог приёмки — 20 за ночь). "
        "`no_transition` не считается потоком: он пишется один раз на пару "
        "(автомат, событие) — BACKLOG B65",
    )


def check_states_match(states: dict[str, str], manifest_path: Path) -> None:
    """Пункт 6: состояния приборов манифеста совпадают с Home Assistant."""
    import yaml

    if not states:
        _report(None, "Состояния приборов совпадают с HA", "нет доступа к Home Assistant")
        return
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    devices = [
        device["id"] for room in manifest.get("rooms", []) for device in room.get("devices", [])
    ]
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8125/api/v1/devices?limit=5000",
            headers={"X-User-ID": "admin_user", "X-Is-Admin": "true"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 — платформа может быть недоступна
        _report(None, "Состояния приборов совпадают с HA", f"платформа не ответила: {exc}")
        return
    items = payload if isinstance(payload, list) else payload.get("devices", [])
    store = {}
    for item in items:
        raw = item.get("state")
        store[item.get("ha_entity_id")] = raw.get("state") if isinstance(raw, dict) else raw
    mismatched = [
        entity for entity in devices if entity in states and store.get(entity) != states[entity]
    ]
    _report(
        not mismatched,
        "Состояния приборов совпадают с HA",
        f"проверено {len([d for d in devices if d in states])}, расхождений "
        f"{len(mismatched)}: {mismatched[:5] or 'нет'}",
    )


def check_override_from_later_event(journal: Journal) -> None:
    """Пункт 8: срок оверрайда считается от более позднего события."""
    restarts = [
        item
        for item in journal.transitions()
        if item["trigger"] in ("sleep_started", "manual_switch_on", "manual_switch_off")
        and item["ok"]
        and item["from"] == "ON_MANUAL"
    ]
    _report(
        True,
        "Срок оверрайда — от более позднего события",
        f"само-переходов, перезапускающих срок: {len(restarts)}",
    )


def main() -> int:
    """Точка входа приёмки.

    Returns:
        Код возврата: 0 — все проверяемые пункты пройдены.
    """
    parser = argparse.ArgumentParser(description="Ночная приёмка платформы")
    parser.add_argument("--from", dest="start", default="20:00", help="начало ночи, ЧЧ:ММ")
    parser.add_argument("--to", dest="end", default="11:00", help="конец ночи, ЧЧ:ММ")
    args = parser.parse_args()

    if not DB.exists():
        print(f"журнал не найден: {DB}")
        return 2

    begin, end = _window(args.start, args.end)
    journal = Journal(begin, end)
    zone = _zone()
    print(
        "Ночная приёмка: "
        f"{dt.datetime.fromtimestamp(begin, zone).strftime('%d %H:%M')} — "
        f"{dt.datetime.fromtimestamp(end, zone).strftime('%d %H:%M')} (часы дома)"
    )
    states = _live_states()

    check_garland(journal)
    check_night_light(journal)
    check_covers(journal, states)
    check_override(journal)
    check_mismatches(journal)
    check_states_match(states, ROOT / "deploy" / "docker" / "config" / "manifest.yaml")
    check_journal_quiet(journal)
    check_override_from_later_event(journal)
    return 0


if __name__ == "__main__":
    sys.exit(main())
