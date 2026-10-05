"""Тесты сохранения манифеста транзакциями жизненного цикла (Known Issue #65).

Дефект: `DeviceLifecycleService` правил манифест в памяти и на этом заканчивал —
у модуля не было доступа к `ManifestStore`, а значит не было и `.save()`. Устройство,
добавленное или удалённое через веб-интерфейс, исчезало после перезапуска, хотя API
отвечал `201` и `success: true`.

Тесты намеренно воспроизводят реальную топологию приложения: `Container.manifest`
загружается через `load_manifest()`, а `ManifestStore` — своим собственным
`load()`. Это **два разных объекта** из одного файла (проверено в контейнере:
`a is b` → `False`). Проверка утверждает содержимое **файла на диске**, а не
состояние заглушки: иначе починка, которая сохраняет устаревший снимок
хранилища, прошла бы тест, ни разу не записав устройство в манифест.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from core.action_handlers import register_all_actions
from core.events.event_bus import EventBus
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.device import Device
from core.models.manifest import BehaviorConfig, Manifest, load_manifest
from core.persistence.manager import PersistenceManager
from core.persistence.manifest_store import ManifestStore
from core.registry import Registry
from services.device_lifecycle import DeviceLifecycleService
from services.device_service import DeviceService
from tests.helpers.device_factory import make_device


MANIFEST_YAML = {
    "version": 1,
    "instance": {
        "id": "test-house",
        "name": "Test House",
        "owner": "test-owner",
        "created_at": "2026-01-01T00:00:00Z",
    },
    "rooms": [
        {
            "id": "kitchen",
            "name": "Кухня",
            "devices": [
                {
                    "id": "light.kitchen",
                    "type": "light",
                    "behaviors": [{"template": "lighting", "priority": 10}],
                }
            ],
        }
    ],
    "automation_rules": {"global_manual_lockout_min": 60},
}


def _entities_on_disk(path: Path) -> set[str]:
    """Читает манифест с диска свежим парсером и возвращает entity_id устройств.

    Args:
        path: Путь к файлу манифеста.

    Returns:
        Множество идентификаторов устройств, записанных в файл.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        device["id"]
        for room in data.get("rooms", [])
        for device in (room.get("devices") or [])
        if device.get("id")
    }


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    """Файл манифеста на диске с одним устройством.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Путь к файлу манифеста.
    """
    path = tmp_path / "manifest.yaml"
    path.write_text(
        yaml.safe_dump(MANIFEST_YAML, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def live_manifest(manifest_path: Path) -> Manifest:
    """Живой манифест сервиса — так же, как `Container.manifest`.

    Отдельный объект от того, что держит `ManifestStore`: именно это расхождение
    и приводило к тихой потере записи.

    Args:
        manifest_path: Путь к файлу манифеста.

    Returns:
        Загруженная модель манифеста.
    """
    return load_manifest(manifest_path)


@pytest.fixture
def store(manifest_path: Path) -> ManifestStore:
    """Хранилище манифеста с собственным снимком состояния.

    Args:
        manifest_path: Путь к файлу манифеста.

    Returns:
        Загруженное хранилище манифеста.
    """
    loaded = ManifestStore(str(manifest_path))
    loaded.load()
    return loaded


@pytest.fixture
def lifecycle(
    tmp_path: Path,
    live_manifest: Manifest,
    store: ManifestStore,
) -> DeviceLifecycleService:
    """Сервис жизненного цикла, подключённый к хранилищу манифеста.

    Args:
        tmp_path: Временный каталог pytest.
        live_manifest: Живой манифест.
        store: Хранилище манифеста.

    Returns:
        Экземпляр DeviceLifecycleService.
    """
    persistence = PersistenceManager(data_dir=tmp_path / "data")
    engine = FSMEngine()
    device_service = DeviceService(
        event_bus=EventBus(),
        persistence_module=persistence,
        ha_adapter=AsyncMock(),
    )
    return DeviceLifecycleService(
        manifest=live_manifest,
        device_service=device_service,
        factory=FSMFactory(engine=engine, registry=_registry(), event_bus=None),
        engine=engine,
        event_router=EventRouter(live_manifest, engine),
        persistence=persistence,
        manifest_store=store,
    )


def _registry() -> Registry:
    """Реестр с зарегистрированными действиями шаблонов.

    Returns:
        Реестр действий.
    """
    registry = Registry()
    register_all_actions(registry)
    return registry


async def test_add_device_should_write_device_to_manifest_file_when_store_provided(
    lifecycle: DeviceLifecycleService,
    manifest_path: Path,
) -> None:
    """Добавленное устройство обязано появиться в файле манифеста.

    Args:
        lifecycle: Сервис жизненного цикла.
        manifest_path: Путь к файлу манифеста.
    """
    await lifecycle.add_device(
        make_device(ha_entity_id="light.novyy", name="Новый свет"),
        room_id="kitchen",
        behaviors=[BehaviorConfig(template="lighting", priority=10)],
    )

    assert "light.novyy" in _entities_on_disk(manifest_path)


async def test_add_device_should_write_live_manifest_not_stale_store_snapshot(
    lifecycle: DeviceLifecycleService,
    store: ManifestStore,
    manifest_path: Path,
) -> None:
    """В файл попадает живой манифест, а не устаревший снимок хранилища.

    Ловушка, ради которой тест написан отдельной проверкой: `ManifestStore.save()`
    пишет `store.current`, а это **другой** объект, чем манифест сервиса. Починка
    вида «передать хранилище и вызвать save()» прошла бы молча, записав в файл
    копию без нового устройства.

    Args:
        lifecycle: Сервис жизненного цикла.
        store: Хранилище манифеста.
        manifest_path: Путь к файлу манифеста.
    """
    live = lifecycle.manifest
    # Снимок хранилища захватывается ДО операции: после сохранения хранилище
    # закономерно перестаёт быть устаревшим, и проверять было бы нечего.
    stale_snapshot = store.current
    assert stale_snapshot is not live, "условие теста: снимок и живой манифест разные объекты"

    await lifecycle.add_device(
        make_device(ha_entity_id="light.novyy"),
        room_id="kitchen",
        behaviors=[BehaviorConfig(template="lighting", priority=10)],
    )

    in_live = any(device.id == "light.novyy" for room in live.rooms for device in room.devices)
    in_stale_snapshot = any(
        device.id == "light.novyy" for room in stale_snapshot.rooms for device in room.devices
    )
    assert in_live is True
    assert in_stale_snapshot is False, "условие теста: снимок остался без нового устройства"
    assert "light.novyy" in _entities_on_disk(manifest_path)


async def test_update_device_should_write_rename_to_manifest_file(
    lifecycle: DeviceLifecycleService,
    manifest_path: Path,
) -> None:
    """Переименование устройства сохраняется в файле манифеста.

    Args:
        lifecycle: Сервис жизненного цикла.
        manifest_path: Путь к файлу манифеста.
    """
    device = make_device(ha_entity_id="light.kitchen", name="Переименованный свет")

    await lifecycle.update_device(
        device,
        room_id="kitchen",
        behaviors=[BehaviorConfig(template="lighting", priority=10)],
    )

    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    names = {
        item["id"]: item.get("name")
        for room in data.get("rooms", [])
        for item in (room.get("devices") or [])
    }
    assert names.get("light.kitchen") == "Переименованный свет"


async def test_delete_device_should_remove_device_from_manifest_file(
    lifecycle: DeviceLifecycleService,
    manifest_path: Path,
) -> None:
    """Удалённое устройство не должно вернуться после перезапуска.

    Args:
        lifecycle: Сервис жизненного цикла.
        manifest_path: Путь к файлу манифеста.
    """
    device = _device_in_manifest(lifecycle)
    assert device is not None, "условие теста: устройство есть в манифесте"

    await lifecycle.delete_device(device, user_id="admin_user")

    assert device.ha_entity_id not in _entities_on_disk(manifest_path)


async def test_add_device_should_raise_and_rollback_when_manifest_save_fails(
    lifecycle: DeviceLifecycleService,
    store: ManifestStore,
    manifest_path: Path,
) -> None:
    """Сбой записи манифеста откатывает комнату и не остаётся тихо пропавшим.

    Args:
        lifecycle: Сервис жизненного цикла.
        store: Хранилище манифеста.
        manifest_path: Путь к файлу манифеста.
    """
    before = _entities_on_disk(manifest_path)

    def _boom() -> None:
        raise OSError("диск недоступен")

    store.save = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="манифест"):
        await lifecycle.add_device(
            make_device(ha_entity_id="light.novyy"),
            room_id="kitchen",
            behaviors=[BehaviorConfig(template="lighting", priority=10)],
        )

    room = next(r for r in lifecycle.manifest.rooms if r.id == "kitchen")
    assert not any(device.id == "light.novyy" for device in room.devices)
    assert _entities_on_disk(manifest_path) == before


async def test_save_manifest_should_keep_cyrillic_readable_in_file(
    lifecycle: DeviceLifecycleService,
    manifest_path: Path,
) -> None:
    """Русские имена в манифесте остаются читаемыми, а не escape-последовательностями.

    `yaml.dump` без `allow_unicode` записывает «Проверка света» как
    `\\u041F\\u0440...`. Файл остаётся валидным YAML, поэтому дефект не виден ни
    валидатору, ни загрузчику — но человек, открывший манифест, видит мусор,
    и прежнее форматирование файла всё равно теряется.

    Args:
        lifecycle: Сервис жизненного цикла.
        manifest_path: Путь к файлу манифеста.
    """
    await lifecycle.add_device(
        make_device(ha_entity_id="light.novyy", name="Свет над столом"),
        room_id="kitchen",
        behaviors=[BehaviorConfig(template="lighting", priority=10)],
    )

    raw = manifest_path.read_text(encoding="utf-8")
    assert "Свет над столом" in raw
    assert "\\u" not in raw, "в файле остались escape-последовательности вместо кириллицы"


async def test_add_device_should_succeed_when_store_not_provided(
    tmp_path: Path,
    live_manifest: Manifest,
) -> None:
    """Автономный режим без хранилища манифеста продолжает работать.

    Args:
        tmp_path: Временный каталог pytest.
        live_manifest: Живой манифест.
    """
    persistence = PersistenceManager(data_dir=tmp_path / "data")
    device_service = DeviceService(
        event_bus=EventBus(),
        persistence_module=persistence,
        ha_adapter=AsyncMock(),
    )
    autonomous = DeviceLifecycleService(
        manifest=live_manifest,
        device_service=device_service,
    )

    result, created = await autonomous.add_device(
        make_device(ha_entity_id="light.avtonomnyy"),
        room_id="kitchen",
        behaviors=[BehaviorConfig(template="lighting", priority=10)],
    )

    assert created is True
    assert result.ha_entity_id == "light.avtonomnyy"


def _device_in_manifest(lifecycle: DeviceLifecycleService) -> Device | None:
    """Восстанавливает устройство из живого манифеста для проверки удаления.

    Args:
        lifecycle: Сервис жизненного цикла.

    Returns:
        Устройство из манифеста либо None, если манифест пуст.
    """
    for room in lifecycle.manifest.rooms:
        for config in room.devices:
            # Имя в манифесте опционально, а модель устройства его требует —
            # без запасного значения фикстура падает на валидации.
            return make_device(ha_entity_id=config.id, name=config.name or config.id)
    return None
