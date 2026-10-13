"""Веб-модель манифеста не теряет поля при сохранении (спека 017, FR-027).

Регресс: модель веб-слоя не описывала ``automation_rules.time_zone``, ``cover``
и ``locations``, и правка манифеста через интерфейс молча вычёркивала их из
файла. ``time_zone`` без этого уезжает в UTC (день/ночь считаются неверно),
``cover`` и ``locations`` теряют правила дома. Тест держит полноту модели.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from webui.models import ManifestModel


MANIFEST = {
    "instance": {"id": "probe", "name": "Probe", "owner": "probe", "created_at": ""},
    "version": 1,
    "rooms": [],
    "locations": [
        {
            "id": "ulitsa",
            "name": "Улица",
            "kind": "outdoor",
            "sensors": {"temperature": "sensor.t"},
        }
    ],
    "automation_rules": {
        "global_manual_lockout_min": 60,
        "time_zone": "Asia/Yekaterinburg",
        "cover": {"feature_entity": "input_boolean.feature_covers"},
        "locations": {"stale_after_sec": 3600, "presence_window_sec": 600},
        "lighting": {"motion_enabled": True},
    },
}


def test_manifest_model_should_keep_automation_rules_sections() -> None:
    """`time_zone`, `cover` и `locations` переживают разбор и выгрузку."""
    dumped = ManifestModel(**MANIFEST).model_dump()

    rules = dumped["automation_rules"]
    assert rules["time_zone"] == "Asia/Yekaterinburg"
    assert rules["cover"]["feature_entity"] == "input_boolean.feature_covers"
    assert rules["locations"]["stale_after_sec"] == 3600
    assert rules["locations"]["presence_window_sec"] == 600


def test_manifest_model_should_keep_locations_section() -> None:
    """Особые зоны наблюдения не теряются."""
    dumped = ManifestModel(**MANIFEST).model_dump()

    assert [location["id"] for location in dumped["locations"]] == ["ulitsa"]
