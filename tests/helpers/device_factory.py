"""Общие помощники для тестов: фабрики данных и посев в постоянное хранилище.

Используются тестами жизненного цикла устройств (specs/006) и контрактными
тестами API устройств, которым раньше требовался прямой доступ к внутреннему
словарю роутов.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from src.core.models.device import Device
from src.core.models.ha_source import HASource
from src.core.models.manifest import BehaviorConfig, DeviceConfig, RoomConfig


def make_device(
    ha_entity_id: str = "light.kitchen",
    source_id: UUID | None = None,
    name: str = "Кухонный свет",
    device_type: str = "light",
    status: str = "available",
    state: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> Device:
    """Создаёт устройство для тестов.

    Args:
        ha_entity_id: Идентификатор сущности Home Assistant.
        source_id: Источник устройства; по умолчанию — новый UUID.
        name: Отображаемое имя устройства.
        device_type: Тип устройства.
        status: Статус доступности.
        state: Текущее состояние.
        config: Пользовательская конфигурация.

    Returns:
        Модель устройства.
    """
    return Device(
        ha_entity_id=ha_entity_id,
        source_id=source_id or uuid4(),
        name=name,
        device_type=device_type,
        state=state if state is not None else {"state": "on"},
        status=status,
        config=config,
    )


def make_source(
    name: str = "Test Home Assistant",
    url: str = "http://192.168.1.100:8123",
    token: str = "test_token_123",
    status: str = "disconnected",
) -> HASource:
    """Создаёт источник Home Assistant для тестов.

    Args:
        name: Название источника.
        url: Адрес Home Assistant.
        token: Токен доступа.
        status: Статус источника.

    Returns:
        Модель источника.
    """
    return HASource(name=name, url=url, token=token, status=status)


def make_room_config(
    room_id: str = "kitchen",
    name: str = "Кухня",
    sensors: dict[str, str] | None = None,
    devices: list[DeviceConfig] | None = None,
) -> RoomConfig:
    """Создаёт комнату манифеста для тестов.

    Args:
        room_id: Идентификатор комнаты.
        name: Название комнаты.
        sensors: Сенсоры комнаты (``тип -> entity_id``).
        devices: Устройства комнаты.

    Returns:
        Модель комнаты.
    """
    return RoomConfig(
        id=room_id,
        name=name,
        sensors=sensors if sensors is not None else {},
        devices=devices or [],
    )


def make_device_config(
    device_id: str = "light.kitchen",
    device_type: str = "light",
    name: str = "Кухонный свет",
    behaviors: list[BehaviorConfig] | None = None,
) -> DeviceConfig:
    """Создаёт устройство манифеста для тестов.

    Args:
        device_id: Идентификатор сущности.
        device_type: Тип устройства.
        name: Отображаемое имя.
        behaviors: Поведения устройства.

    Returns:
        Модель устройства манифеста.
    """
    return DeviceConfig(
        id=device_id,
        type=device_type,
        name=name,
        behaviors=behaviors or [BehaviorConfig(template="lighting", priority=10)],
    )


def make_persistence(data_dir: Path | str) -> Any:
    """Создаёт менеджер хранения в изолированном временном каталоге.

    Args:
        data_dir: Каталог для файлов данных.

    Returns:
        Экземпляр ``PersistenceManager`` (импорт локальный ради изоляции тестов).
    """
    from src.core.persistence.manager import PersistenceManager

    return PersistenceManager(data_dir=data_dir)


async def seed_persistence(persistence: Any, devices: list[Device]) -> None:
    """Записывает устройства в постоянное хранилище.

    Args:
        persistence: Менеджер хранения.
        devices: Устройства для посева.
    """
    for device in devices:
        await persistence.devices.save_device(device)


def seed_device_in_service(device_service: Any, device: Device) -> Device:
    """Кладёт устройство в память сервиса устройств (только для тестов).

    Не пишет в постоянное хранилище, чтобы тесты оставались герметичными:
    используется фикстурами, которым нужно «живое» устройство в единственном
    источнике, но не нужно проверять его запись на диск.

    Args:
        device_service: Экземпляр ``DeviceService``.
        device: Устройство для посева.

    Returns:
        Посеянное устройство.
    """
    device_service._devices[device.id] = device
    device_service._index.add_device(device)
    return device
