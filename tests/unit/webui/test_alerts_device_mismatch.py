"""Расхождение «автомат ↔ прибор» обязано быть тревогой (спека 017, концепция §7).

Боевой повод — 2026-10-14: на рассвете автомат ночного освещения ушёл в `OFF`,
а уличные лампы остались гореть. Сторож это увидел, но увидеть было негде:
проблемы сторожа не попадали ни в готовность, ни в тревоги интерфейса.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from webui.services.alerts import (
    KIND_DEVICE_MISMATCH,
    SEVERITY_WARNING,
    alerts_from_watchdog,
)


DEVICE = "light.group_nochnoe_osveshcheni"


def _entry(**fields: Any) -> Any:
    """Запись снимка сторожа с нужными полями.

    Args:
        **fields: Значения полей записи.

    Returns:
        Запись-двойник.
    """
    base = {"entity_id": f"{DEVICE}_deco_light_10", "device": DEVICE, "state": "OFF"}
    base.update(fields)
    return SimpleNamespace(**base)


def test_mismatch_becomes_alert() -> None:
    """«Горит, хотя решение — выключено» становится тревогой с объяснением."""
    snapshot = SimpleNamespace(
        entries=(_entry(device_state="on", mismatch_reason="device_on_decision_off"),)
    )

    alerts = alerts_from_watchdog(snapshot)

    assert len(alerts) == 1
    assert alerts[0].kind == KIND_DEVICE_MISMATCH
    assert alerts[0].subject == DEVICE
    assert alerts[0].severity == SEVERITY_WARNING
    assert "выключено" in alerts[0].detail


def test_matching_entries_are_ignored() -> None:
    """Согласный прибор тревоги не порождает."""
    snapshot = SimpleNamespace(entries=(_entry(device_state="off", mismatch_reason=None),))

    assert alerts_from_watchdog(snapshot) == []


def test_unavailable_device_is_explained() -> None:
    """Недоступный прибор объясняется словами, а не кодом расхождения."""
    snapshot = SimpleNamespace(
        entries=(_entry(device_state="unavailable", mismatch_reason="device_unavailable"),)
    )

    alerts = alerts_from_watchdog(snapshot)

    assert alerts[0].detail.endswith("(Home Assistant сообщает: unavailable)")
    assert "не отвечает" in alerts[0].detail


def test_cover_mismatch_speaks_of_position() -> None:
    """Про штору говорят «закрыта», а не «не горит»."""
    snapshot = SimpleNamespace(
        entries=(
            _entry(
                entity_id="cover.shtora_v_spalne_cover_modes_10",
                device="cover.shtora_v_spalne",
                state="OPEN",
                device_state="closed",
                mismatch_reason="device_off_decision_on",
            ),
        )
    )

    alerts = alerts_from_watchdog(snapshot)

    assert "закрыта, хотя решение — открыть" in alerts[0].detail


def test_manual_override_alert_is_informational() -> None:
    """Уступка человеку — «знать», а не «вмешаться»."""
    snapshot = SimpleNamespace(
        entries=(
            _entry(
                device="cover.shtora_v_kabinete",
                state="OPEN",
                device_state="closed",
                mismatch_reason="manual_override_active",
            ),
        )
    )

    alerts = alerts_from_watchdog(snapshot)

    assert alerts[0].severity == "info"
    assert "человек вмешался" in alerts[0].detail


def test_no_snapshot_is_empty() -> None:
    """Сторожа ещё не было — тревог нет, а не ошибка."""
    assert alerts_from_watchdog(None) == []
