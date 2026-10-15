"""Испорченный файл данных — это не «данных нет» (аудит 2026-10-16, К-6).

Тот же урок, что уже прошло хранилище истории операций (research R6): молчаливое
чтение пустоты и есть путь к потере. Хранилище отдавало пустой список на любую
ошибку, включая намеренно брошенное ``PersistenceCorruptedError``; гидратация
видела «устройств нет» и молчала, а следующая запись затирала испорченный файл
пустым состоянием — данные исчезали бессрочно, и единственным следом оставалась
строка в журнале.

Различие ради этого и заводили: рядом с испорченным файлом остаётся копия
``.corrupt-<ts>``, а вызывающий обязан узнать о поломке.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from core.persistence.atomic import PersistenceCorruptedError
from core.persistence.devices import DeviceAccessPersistence, DevicePersistence
from core.persistence.sources import HASourcePersistence


class TestCorruptFileIsNotAnEmptyStore:
    """Поломка обязана дойти до вызывающего, а не выглядеть пустотой."""

    async def test_devices_corruption_raises(self, tmp_path: Path) -> None:
        """Испорченный ``devices.json`` не отдаётся пустым списком.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        persistence = DevicePersistence(data_dir=tmp_path)
        persistence.devices_file.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(PersistenceCorruptedError):
            await persistence.load_all_devices()

    async def test_accesses_corruption_raises(self, tmp_path: Path) -> None:
        """Испорченный ``device_access.json`` не отдаётся пустым списком.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        persistence = DeviceAccessPersistence(data_dir=tmp_path)
        persistence.access_file.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(PersistenceCorruptedError):
            await persistence.load_all_accesses()

    async def test_sources_corruption_raises(self, tmp_path: Path) -> None:
        """Испорченный ``sources.json`` не отдаётся пустым списком.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        persistence = HASourcePersistence(data_dir=tmp_path)
        persistence.sources_file.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(PersistenceCorruptedError):
            await persistence.load_all_sources()

    async def test_missing_files_still_mean_an_empty_store(self, tmp_path: Path) -> None:
        """Отсутствие файлов остаётся «данных нет» — различие сохраняется.

        Args:
            tmp_path: Временный каталог.

        Returns:
            Ничего.
        """
        assert await DevicePersistence(data_dir=tmp_path).load_all_devices() == []
        assert await HASourcePersistence(data_dir=tmp_path).load_all_sources() == []
