"""Манифест дома не должен уменьшаться молча (#88).

Две ночи подряд платформа переписывала состав дома целиком: сначала из
тринадцати комнат осталось шесть, затем применение пачки устройств записало
файл тринадцать раз за секунду и добавило в кухню двадцать светильников. Манифест
— источник истины о том, чем платформа управляет, и потеря комнат в нём означает,
что часть дома выпала из автоматики навсегда и молча.

Здесь проверяется страховка, а не путь записи: хранилище обязано отказать, если
в новой модели потерялось то, что было на диске, и не трогать файл. Явное
удаление устройства — другой случай и отдельный флаг.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.models.manifest import Manifest
from core.persistence.manifest_store import ManifestShrinkError, ManifestStore


def _manifest_with(*rooms: tuple[str, list[str]]) -> Manifest:
    """Собрать манифест с заданными комнатами и устройствами.

    Args:
        *rooms: Пары «id комнаты — id устройств».

    Returns:
        Модель манифеста.
    """
    from core.models.manifest import DeviceConfig, InstanceConfig, RoomConfig

    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=room_id,
                name=room_id.title(),
                sensors={},
                devices=[DeviceConfig(id=device_id, type="light") for device_id in devices],
            )
            for room_id, devices in rooms
        ],
    )


def _write(path: Path, manifest: Manifest) -> None:
    """Положить манифест на диск.

    Args:
        path: Куда писать.
        manifest: Что писать.
    """
    path.write_text(yaml.dump(manifest.model_dump(), allow_unicode=True), encoding="utf-8")


def _store(path: Path) -> ManifestStore:
    """Хранилище, уже прочитавшее файл.

    Args:
        path: Файл манифеста.

    Returns:
        Готовое хранилище.
    """
    store = ManifestStore(str(path))
    store.load()
    return store


def _on_disk(path: Path) -> dict[str, Any]:
    """Прочитать файл манифеста как есть.

    Args:
        path: Файл манифеста.

    Returns:
        Разобранное содержимое.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class TestSilentShrinkIsRefused:
    """Потеря комнат и устройств не проходит молча."""

    def test_rooms_loss_is_refused(self, tmp_path: Path) -> None:
        """Манифест с меньшим числом комнат не записывается."""
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a"]), ("spalnia", ["light.b"])))
        store = _store(path)

        store.current = _manifest_with(("spalnia", ["light.b"]))

        with pytest.raises(ManifestShrinkError):
            store.save()

        assert len(_on_disk(path)["rooms"]) == 2, (
            "файл манифеста переписан без комнаты: тихое уменьшение описания дома "
            "и есть та потеря, из-за которой дом выпал из автоматики"
        )

    def test_device_loss_is_refused(self, tmp_path: Path) -> None:
        """Манифест с fewer устройствами не записывается."""
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a", "light.b"])))
        store = _store(path)

        store.current = _manifest_with(("kitchen", ["light.a"]))

        with pytest.raises(ManifestShrinkError):
            store.save()

        assert len(_on_disk(path)["rooms"][0]["devices"]) == 2, (
            "устройство исчезло из манифеста без явного удаления: уменьшение "
            "состава дома не должно проходить молча"
        )

    def test_room_loss_is_refused_even_if_other_room_grew(self, tmp_path: Path) -> None:
        """Рост другой комнаты не оправдывает потерю соседней.

        Именно так выглядел вечерний случай: в кухню добавили двадцать
        устройств, а семь комнат при этом исчезли — по числу устройств выглядело
        как рост, а по составу дома это была потеря.
        """
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", []), ("spalnia", []), ("sad", [])))
        store = _store(path)

        store.current = _manifest_with(("kitchen", [f"light.new_{i}" for i in range(20)]))

        with pytest.raises(ManifestShrinkError):
            store.save()

        assert len(_on_disk(path)["rooms"]) == 3

    def test_explicit_removal_is_allowed(self, tmp_path: Path) -> None:
        """Явное удаление — другой случай: флаг это разрешает."""
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a", "light.b"])))
        store = _store(path)

        store.current = _manifest_with(("kitchen", ["light.a"]))
        store.save(allow_removal=True)

        assert len(_on_disk(path)["rooms"][0]["devices"]) == 1


class TestSafeWrites:
    """Обычная работа хранилища не ломается."""

    def test_growth_is_written(self, tmp_path: Path) -> None:
        """Добавление комнаты и устройства записывается как прежде."""
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a"])))
        store = _store(path)

        store.current = _manifest_with(("kitchen", ["light.a"]), ("spalnia", ["light.b"]))
        store.save()

        on_disk = _on_disk(path)
        assert len(on_disk["rooms"]) == 2
        assert on_disk["rooms"][1]["devices"][0]["id"] == "light.b"

    def test_identical_content_does_not_touch_files(self, tmp_path: Path) -> None:
        """Запись без изменений не трогает ни файл, ни резервную копию.

        Момент важен именно после потери: пока хранилище писало файл при каждом
        обращении, резервная копия `.bak` перезаписывалась тем же содержимым и
        точка отката исчезала.
        """
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a"])))
        store = _store(path)
        backup_path = tmp_path / "manifest.yaml.bak"

        store.save()

        assert not backup_path.exists(), (
            "резервная копия создана при записи, которой не было: она должна "
            "появляться только когда файл действительно меняется"
        )

    def test_backup_holds_previous_state(self, tmp_path: Path) -> None:
        """Перед изменением в `.bak` лежит состояние, из которого откатываются."""
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a"])))
        store = _store(path)

        store.current = _manifest_with(("kitchen", ["light.a", "light.b"]))
        store.save()

        backup = yaml.safe_load((tmp_path / "manifest.yaml.bak").read_text(encoding="utf-8"))
        assert len(backup["rooms"][0]["devices"]) == 1, (
            "в резервной копии должно лежать состояние до изменения, иначе откатываться некуда"
        )


class TestBatch:
    """Пачка изменений пишется один раз."""

    def test_batch_writes_once(self, tmp_path: Path) -> None:
        """Несколько изменений подряд — одна запись и одна резервная копия."""
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a"])))
        store = _store(path)
        # Считаются именно записи на диск, а не вызовы save(): внутри пачки
        # save() зовётся на каждое изменение — так и должно быть, записывает
        # файл только выход из блока.
        writes: list[bool] = []
        original_write = store._write  # noqa: SLF001

        def counting_write(**kwargs: Any) -> None:
            writes.append(True)
            original_write(**kwargs)

        store._write = counting_write  # type: ignore[method-assign]  # noqa: SLF001

        with store.batch():
            store.current = _manifest_with(("kitchen", ["light.a", "light.b"]))
            store.save()
            store.current = _manifest_with(("kitchen", ["light.a", "light.b", "light.c"]))
            store.save()
            store.current = _manifest_with(
                ("kitchen", ["light.a", "light.b", "light.c", "light.d"])
            )
            store.save()

        assert len(writes) == 1, (
            f"пачка из трёх изменений записана на диск {len(writes)} раз(а): каждая "
            "запись перетирала резервную копию, и точка отката исчезала"
        )
        assert len(_on_disk(path)["rooms"][0]["devices"]) == 4, (
            "после пачки в файле должно быть конечное состояние, а не первое"
        )

    def test_batch_without_changes_writes_nothing(self, tmp_path: Path) -> None:
        """Пачка без изменений не создаёт файлов.

        Args:
            tmp_path: Временный каталог.
        """
        path = tmp_path / "manifest.yaml"
        _write(path, _manifest_with(("kitchen", ["light.a"])))
        store = _store(path)

        with store.batch():
            store.current = _manifest_with(("kitchen", ["light.a"]))
            store.save()

        assert not (tmp_path / "manifest.yaml.bak").exists()
