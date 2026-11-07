"""Manifest models for Smart Home Platform v3.1.

Room-based architecture:
- Rooms contain sensors (inputs) and devices (actuators)
- Sensors describe room state
- Devices react to processed sensor events
- Same sensor entity can be referenced from multiple rooms
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from core.models.manifest_base import (
    BehaviorConfig as BehaviorConfig,
    DeviceConfig as DeviceConfig,
    InstanceConfig as InstanceConfig,
    LocationConfig as LocationConfig,
    RoomConfig as RoomConfig,
    SensorBinding as SensorBinding,
    SensorMap as SensorMap,
    StrictModel,
    all_sensor_entities as all_sensor_entities,
    iter_role_entities as iter_role_entities,
    role_entities as role_entities,
)
from core.models.manifest_rules import (
    AutomationClimateRules as AutomationClimateRules,
    AutomationDomainRules as AutomationDomainRules,
    AutomationRules as AutomationRules,
    HouseSchedule as HouseSchedule,
    LocationRules as LocationRules,
    SensorHealthRules as SensorHealthRules,
)


class Dashboard(StrictModel):
    """Dashboard configuration for Lovelace generation."""

    title: str = ""
    rooms: list[str] = Field(default_factory=list)
    show_sensors: bool = True
    show_devices: bool = True
    show_platform: bool = True
    """Показывать ли сводку платформы: сколько проблем в доме и какие.

    Выключить стоит дому без MQTT: сущность «Проблемы в доме» создаёт зеркало
    платформы, и без него карточка ссылалась бы на несуществующую сущность
    (именно так дашборд однажды открылся с «сущность недоступна»).
    """


class Manifest(StrictModel):
    battery_types: dict[str, str] = Field(default_factory=dict)
    """Тип батарейки по сущности: ``sensor.…_battery`` → ``CR2032``.

    Требование владельца 2026-10-15: в тревоге о севшей батарейке и в сведениях о
    датчике должно быть видно, **какую** батарейку покупать. Тип знает только
    владелец: Home Assistant его не отдаёт, а угадывание по модели ошибается.
    """
    """Root manifest model for room-based architecture."""

    instance: InstanceConfig
    version: int = 1
    rooms: list[RoomConfig] = Field(default_factory=list)
    #: Особые зоны наблюдения вне комнат (спека 016): улица, грядки. Комнаты
    #: тоже локации и описываются как раньше — в ``rooms``.
    locations: list[LocationConfig] = Field(default_factory=list)
    automation_rules: AutomationRules = Field(default_factory=AutomationRules)
    dashboard: Dashboard = Field(default_factory=Dashboard)
    extensions: dict[str, Any] = Field(default_factory=dict)
    """Явные расширения описания дома.

    Единственное место, где допускаются поля, которых нет в модели. Всё
    остальное неизвестное отклоняется: опечатка не должна молча выключать
    настройку.
    """

    @property
    def devices(self) -> list[DeviceConfig]:
        """Flat list of all devices across all rooms."""
        return [device for room in self.rooms for device in room.devices]

    @property
    def zones(self) -> list[RoomConfig]:
        """Alias for rooms (backward compat with old Zone model)."""
        return self.rooms

    @property
    def all_places(self) -> list[RoomConfig | LocationConfig]:
        """Все места дома: комнаты и локации (спека 016).

        Место — то, где живут датчики и приборы. Комната и локация различаются
        **расположением** (в доме или на улице), а не устройством: автоматика
        прибора строится одинаково (требование владельца 2026-10-19). Прежде
        автоматы собирались только для комнат, и перенос места в локации молча
        выключал его автоматику.

        Returns:
            Список мест: сначала комнаты, затем локации.
        """
        return [*self.rooms, *self.locations]

    @model_validator(mode="after")
    def validate_place_tree(self) -> Manifest:
        """Проверить дерево мест: идентификаторы, родителей и циклы.

        Места — одно пространство имён (B93): комната ``sad`` и локация ``sad``
        одновременно сделали бы вложенность неоднозначной, а правило «Теплица в
        саду» — невыразимым. Проверка стоит в модели, а не в интерфейсе: правило
        должно действовать для любого способа правки манифеста.

        Returns:
            Тот же манифест.

        Raises:
            ValueError: Если идентификатор повторяется, родитель не найден, есть
                цикл или локация вложена в комнату.
        """
        by_id: dict[str, RoomConfig | LocationConfig] = {}
        for place in self.all_places:
            if place.id in by_id:
                raise ValueError(
                    f"Место '{place.id}' описано дважды: комнаты и локации делят "
                    f"одно пространство имён"
                )
            by_id[place.id] = place

        for place in self.all_places:
            parent_id = place.parent
            if parent_id is None:
                continue
            parent = by_id.get(parent_id)
            if parent is None:
                raise ValueError(
                    f"Место '{place.id}' ссылается на неизвестного родителя '{parent_id}'"
                )
            if parent_id == place.id:
                raise ValueError(f"Место '{place.id}' не может быть родителем само себе")
            if isinstance(place, LocationConfig) and isinstance(parent, RoomConfig):
                raise ValueError(
                    f"Локация '{place.id}' не может вкладываться в комнату "
                    f"'{parent_id}': комнаты — это внутренние помещения"
                )

        for place in self.all_places:
            seen = {place.id}
            current = by_id.get(place.parent) if place.parent else None
            while current is not None:
                if current.id in seen:
                    raise ValueError(f"Цикл во вложенности мест: '{place.id}' замкнут сам на себя")
                seen.add(current.id)
                current = by_id.get(current.parent) if current.parent else None

        return self

    def place(self, place_id: str) -> RoomConfig | LocationConfig | None:
        """Найти место по идентификатору — комнату или локацию.

        Args:
            place_id: Идентификатор места.

        Returns:
            Место либо ``None``.
        """
        return next((place for place in self.all_places if place.id == place_id), None)

    def children(self, place_id: str | None) -> list[RoomConfig | LocationConfig]:
        """Непосредственные дети места.

        Args:
            place_id: Идентификатор родителя; ``None`` — места верхнего уровня.

        Returns:
            Дети в порядке объявления.
        """
        return [place for place in self.all_places if place.parent == place_id]

    def place_path(self, place_id: str) -> list[RoomConfig | LocationConfig]:
        """Путь от корня до места — для «хлебных крошек» и порядка на панели.

        Args:
            place_id: Идентификатор места.

        Returns:
            Список мест от верхнего к запрошенному; пустой, если места нет.
        """
        path: list[RoomConfig | LocationConfig] = []
        current = self.place(place_id)
        seen: set[str] = set()
        while current is not None:
            if current.id in seen:  # защита от повреждённого дерева
                break
            seen.add(current.id)
            path.append(current)
            current = self.place(current.parent) if current.parent else None
        return list(reversed(path))

    @property
    def all_devices(self) -> list[tuple[str, DeviceConfig]]:
        """Flat list of (place_id, device) for iteration."""
        return [(place.id, device) for place in self.all_places for device in place.devices]

    @property
    def all_device_ids(self) -> list[str]:
        """Flat list of all device IDs."""
        return [device.id for _, device in self.all_devices]

    def get_room_for_device(self, device_id: str) -> RoomConfig | LocationConfig | None:
        """Найти место прибора — комнату или локацию.

        Имя оставлено прежним для совместимости, но ищет по всем местам: прибор
        локации — такое же место, как прибор комнаты.

        Args:
            device_id: Идентификатор прибора.

        Returns:
            Место прибора либо ``None``.
        """
        for place in self.all_places:
            if any(d.id == device_id for d in place.devices):
                return place
        return None

    def get_device(self, device_id: str) -> DeviceConfig | None:
        """Find a device by ID across all rooms."""
        for _, device in self.all_devices:
            if device.id == device_id:
                return device
        return None

    def get_sensors_for_device(self, device_id: str) -> SensorMap:
        """Датчики места, к которому относится прибор.

        Args:
            device_id: Идентификатор прибора.

        Returns:
            Привязка «роль → сущность» места либо пустая карта.
        """
        place = self.get_room_for_device(device_id)
        return place.sensors if place else {}


# ─── Backward compatibility aliases ───────────────────────────────────────────
# Старые имена для совместимости с существующими тестами и модулями

ClimateAutomation = AutomationDomainRules
LightingAutomation = AutomationDomainRules
VentilationAutomation = AutomationDomainRules
AnyDevice = DeviceConfig
LightMotionDevice = DeviceConfig


# ─── Loader function (kept here for import compatibility) ─────────────────────


def load_manifest(manifest_path: str | Path) -> Manifest:
    """Load and validate manifest from YAML file.

    Args:
        manifest_path: Path to manifest YAML file.

    Returns:
        Validated Manifest instance.

    Raises:
        FileNotFoundError: If manifest file doesn't exist.
        pydantic.ValidationError: If manifest is invalid.
    """
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Манифест дома не найден: {path}\n"
            "Платформа описывает дом манифестом: комнаты, локации, приборы и правила.\n"
            "Что делать:\n"
            "  1) укажите свой дом через CONFIG_PATH — каталог, в котором лежит "
            "manifest.yaml:\n"
            "       CONFIG_PATH=/путь/к/дому\n"
            "  2) либо положите manifest.yaml по этому пути.\n"
            "Образец для нового дома: instances/leonids_house/manifest.yaml\n"
            "Эталон боевого дома: instances/leonids_house_prod/manifest.yaml"
        )

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return Manifest.model_validate(data)


# Zone в новой архитектуре = Room
class Zone(StrictModel):
    """Zone is now an alias for RoomConfig with optional floor."""

    id: str
    name: str
    floor: int = 1
    sensors: dict[str, str] = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)


InstanceInfo = InstanceConfig
