"""Совместимость манифеста прежней версии (спека 018, US1).

Старый документ должен загружаться без потери данных; недостающие значения
получают задокументированные умолчания, а не превращаются в ошибку.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from core.models.manifest import Manifest, load_manifest


INSTANCES = Path("instances")


def test_minimal_manifest_gets_defaults() -> None:
    """Минимальный документ получает умолчания, а не отказ."""
    manifest = Manifest.model_validate(
        {
            "instance": {"id": "probe", "name": "Probe", "owner": "probe", "created_at": ""},
            "version": 1,
        }
    )

    assert manifest.rooms == []
    assert manifest.locations == []
    assert manifest.dashboard.title == ""
    assert manifest.extensions == {}


def test_known_optional_sections_survive_loading() -> None:
    """Необязательные разделы, появившиеся позже, не теряются."""
    manifest = load_manifest(INSTANCES / "leonids_house" / "manifest.yaml")

    dumped = manifest.model_dump()

    assert "time_zone" in dumped["instance"]
    assert "cover" in dumped["automation_rules"]
    assert "locations" in dumped
