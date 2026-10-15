"""Отказ без манифеста должен быть понятным (переносимость, BACKLOG B78).

Тот, кто поднимает платформу впервые на своём Home Assistant, не знает ни про
`CONFIG_PATH`, ни про то, что дом описывается манифестом. Раньше он получал
`Manifest not found: /config/behavioral_platform/manifest.yaml` — по такой
строке непонятно ни что случилось, ни что делать.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from core.models.manifest import load_manifest


class TestManifestMissing:
    """Манифеста нет — платформа объясняет, как его задать."""

    def test_message_tells_where_and_how(self, tmp_path: Path) -> None:
        """В сообщении есть путь, `CONFIG_PATH` и образцы манифеста.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        missing = tmp_path / "нет-такого-дома" / "manifest.yaml"

        with pytest.raises(FileNotFoundError) as exc_info:
            load_manifest(missing)

        message = str(exc_info.value)
        assert str(missing) in message, "в отказе нет пути, куда платформа смотрела"
        assert "CONFIG_PATH" in message, "не сказано, как указать свой дом"
        assert "instances/leonids_house" in message, "нет образца манифеста"

    def test_existing_manifest_still_loads(self, tmp_path: Path) -> None:
        """Загружаемый манифест работает как прежде — понятный отказ не сломал загрузку.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        sample = Path("instances/leonids_house/manifest.yaml")
        assert sample.exists(), "образец манифеста пропал из репозитория"

        manifest = load_manifest(sample)

        assert manifest.instance.name, "у загруженного манифеста нет имени дома"
