"""Веб-модель манифеста сохраняет вложенные поля правил (спека 017, FR-027).

Регресс 2026-10-14: правка манифеста через интерфейс затирала **вложенные** поля
правил значениями по умолчанию — `climate.setpoint_entity`, `lighting.quiet_from`,
`ventilation.enable_entity`, `cover.night_close_entity` и другие. Из-за этого
вентиляция отказывала `guard_data_missing`, шторы не закрывались ночью, а свет
включался на полную яркость в тихие часы. Тест держит полноту вложенных полей —
именно его не хватало, чтобы дефект поймали тесты.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from webui.models import ManifestModel


MANIFEST = {
    "instance": {"id": "p", "name": "P", "owner": "p", "created_at": ""},
    "version": 1,
    "rooms": [],
    "automation_rules": {
        "global_manual_lockout_min": 60,
        "time_zone": "Asia/Yekaterinburg",
        "lighting": {
            "quiet_from": "23:00",
            "quiet_to": "06:30",
            "night_off_at": "23:00",
            "morning_at": "07:00",
            "night_motion_rooms": ["sanuzel", "konteiner"],
            "always_on_motion_rooms": ["sanuzel"],
            "sleep_modifier": "input_boolean.sleep_mode",
            "battery_watch_entities": ["sensor.battery"],
        },
        "climate": {
            "setpoint_entity": "input_number.temperatura",
            "comfort_max_entity": "input_number.maksimalno_komfortnaia_temperatura",
            "season_entity": "input_boolean.zima",
            "ac_gate_entity": "input_boolean.ispolzovat_konditsioner",
            "thermostat_entity": "climate.termostat_gostinaia",
            "setpoint_min": 5.0,
            "setpoint_max": 30.0,
        },
        "ventilation": {
            "enable_entity": "input_boolean.ventiliatsiia",
            "airing_entity": "input_boolean.provetrivanie",
            "exhaust_entity": "input_boolean.provetrivanie_vytyazhka",
            "outside_temp_entity": "sensor.temperatura_na_ulitse_srednee",
        },
        "cover": {
            "feature_entity": "input_boolean.feature_covers",
            "my_doma_entity": "input_boolean.my_doma",
            "night_close_entity": "input_boolean.zakryvat_shtory_nochiu",
            "emergency_entity": "input_boolean.covers_emergency_open",
        },
    },
}


def _rules() -> dict:
    """Правила дома после разбора и выгрузки.

    Returns:
        Словарь `automation_rules`.
    """
    return ManifestModel(**MANIFEST).model_dump()["automation_rules"]


def test_lighting_rules_should_survive_roundtrip() -> None:
    """Тихие часы, ночные комнаты и расписание света не теряются."""
    lighting = _rules()["lighting"]

    assert lighting["quiet_from"] == "23:00"
    assert lighting["quiet_to"] == "06:30"
    assert lighting["night_off_at"] == "23:00"
    assert lighting["morning_at"] == "07:00"
    assert lighting["night_motion_rooms"] == ["sanuzel", "konteiner"]
    assert lighting["sleep_modifier"] == "input_boolean.sleep_mode"


def test_climate_rules_should_survive_roundtrip() -> None:
    """Сущности климата (уставка, комфорт, сезон) не теряются."""
    climate = _rules()["climate"]

    assert climate["setpoint_entity"] == "input_number.temperatura"
    assert climate["comfort_max_entity"] == "input_number.maksimalno_komfortnaia_temperatura"
    assert climate["season_entity"] == "input_boolean.zima"
    assert climate["setpoint_min"] == 5.0


def test_ventilation_rules_should_survive_roundtrip() -> None:
    """Сущности вентиляции (выключатель, проветривание, вытяжка) не теряются."""
    ventilation = _rules()["ventilation"]

    assert ventilation["enable_entity"] == "input_boolean.ventiliatsiia"
    assert ventilation["airing_entity"] == "input_boolean.provetrivanie"
    assert ventilation["exhaust_entity"] == "input_boolean.provetrivanie_vytyazhka"


def test_cover_rules_should_survive_roundtrip() -> None:
    """Флаги штор (ночное закрытие, аварийный) не теряются."""
    cover = _rules()["cover"]

    assert cover["night_close_entity"] == "input_boolean.zakryvat_shtory_nochiu"
    assert cover["emergency_entity"] == "input_boolean.covers_emergency_open"
