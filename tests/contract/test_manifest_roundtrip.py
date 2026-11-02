"""Один источник описания дома: round-trip без потерь (спека 018, US1).

Проверяется не «модель что-то приняла», а что каждое поле, прочитанное из YAML,
переживает `model_dump` → `model_validate` без потерь и остаётся доступным
исполнению.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.models.manifest import Manifest, load_manifest


PROD_MANIFEST = Path("instances/leonids_house_prod/manifest.yaml")
TEST_MANIFEST = Path("instances/leonids_house/manifest.yaml")


@pytest.mark.parametrize("path", [PROD_MANIFEST, TEST_MANIFEST])
def test_manifest_survives_dump_and_load(path: Path) -> None:
    """Манифест не теряет данные при повторной загрузке.

    Args:
        path: Проверяемый манифест.
    """
    manifest = load_manifest(path)
    dumped = manifest.model_dump()

    again = Manifest.model_validate(dumped)

    assert again.model_dump() == dumped, (
        f"{path}: повторная загрузка изменила описание дома — "
        "это и есть класс дефектов «сохранилось, но не применилось»"
    )


def test_every_top_level_field_is_present_in_dump() -> None:
    """Все объявленные поля модели присутствуют в сериализованном виде."""
    manifest = load_manifest(PROD_MANIFEST)
    dumped = manifest.model_dump()

    missing = set(Manifest.model_fields) - set(dumped)

    assert not missing, f"поля модели пропали при сериализации: {sorted(missing)}"


def test_raw_yaml_is_revalidated_by_the_same_model() -> None:
    """YAML-документ и его model_dump дают одну и ту же модель."""
    raw = yaml.safe_load(PROD_MANIFEST.read_text(encoding="utf-8"))
    from_raw = Manifest.model_validate(raw)
    from_dump = Manifest.model_validate(from_raw.model_dump())

    assert from_raw.model_dump() == from_dump.model_dump()
