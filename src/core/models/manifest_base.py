"""Base manifest models and sensor helpers (spec 018, T059)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Базовая модель манифеста: неизвестные поля — ошибка.

    Опечатка в имени поля должна быть видна сразу, а не превращаться в
    молчаливо проигнорированную настройку. Явные расширения допускаются только
    через поле ``extensions``.
    """

    model_config = ConfigDict(extra="forbid")


#: Привязка роли датчика: одна сущность или несколько.
#:
#: Несколько сущностей нужны там, где одну роль закрывают разные устройства:
#: две камеры на террасе дают и движение, и детекции «человек/животное/машина».
#: Снимок локации и раньше умел «роль → список показаний», схема манифеста —
#: нет; теперь умеет и она.
SensorBinding = str | list[str]

#: Роль датчика → сущность или список сущностей.
SensorMap = dict[str, SensorBinding]


def iter_role_entities(sensors: Mapping[str, SensorBinding] | None) -> Iterator[tuple[str, str]]:
    """Развернуть привязки датчиков в пары «роль — сущность».

    Args:
        sensors: Привязки локации или комнаты.

    Yields:
        Пары «роль, сущность» — по одной на каждую сущность роли.
    """
    for role, value in (sensors or {}).items():
        if isinstance(value, str):
            yield role, value
        else:
            for entity in value or []:
                yield role, entity


def role_entities(sensors: Mapping[str, SensorBinding] | None, role: str) -> list[str]:
    """Сущности одной роли.

    Args:
        sensors: Привязки локации или комнаты.
        role: Роль датчика.

    Returns:
        Список сущностей (пустой, если роли нет).
    """
    value = (sensors or {}).get(role)
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def all_sensor_entities(sensors: Mapping[str, SensorBinding] | None) -> list[str]:
    """Все сущности датчиков без повторов, в исходном порядке.

    Args:
        sensors: Привязки локации или комнаты.

    Returns:
        Список сущностей.
    """
    seen: set[str] = set()
    result: list[str] = []
    for _, entity in iter_role_entities(sensors):
        if entity and entity not in seen:
            seen.add(entity)
            result.append(entity)
    return result


class InstanceConfig(StrictModel):
    """Platform instance metadata."""

    id: str
    name: str
    owner: str = ""
    created_at: str = ""
    time_zone: str | None = None
    """Часовой пояс дома.

    Это свойство дома, а не правил автоматизации: пояс нужен и фабрике
    автоматов, и службе цветовой температуры, и суточному циклу (аудит B76,
    A9). Пустое значение — пояс процесса.
    """


class BehaviorConfig(StrictModel):
    """Behavior template with priority and params."""

    template: str
    priority: int = 10
    params: dict[str, Any] = Field(default_factory=dict)


class DeviceConfig(StrictModel):
    """Device as an actuator inside a room."""

    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = Field(default_factory=list)


class RoomConfig(StrictModel):
    """Room: container for sensors and devices.

    Sensors describe room state (inputs).
    Devices are actuators that react to processed events (outputs).
    Same sensor entity_id can appear in multiple rooms.
    """

    id: str
    name: str
    kind: str = "room"
    """Вид места. У комнаты — ``room``; вид нужен, чтобы комната и локация
    описывались одним понятием (B93)."""
    parent: str | None = None
    """Место верхнего уровня, в которое входит эта комната (id)."""
    sensors: SensorMap = Field(default_factory=dict)
    thermostat_entity: str | None = None
    """Термостат этой комнаты (``climate.*``), если он есть.

    Термостат — свойство комнаты, а не дома: в гостиной стоит штатный
    термостат, который держит свою уставку (аудит B76, A6). Платформа
    синхронизирует его с общей уставкой дома, но не приписывает его другим
    комнатам.
    """
    devices: list[DeviceConfig] = Field(default_factory=list)

    @field_validator("sensors")
    @classmethod
    def validate_sensor_ids(cls, v: SensorMap) -> SensorMap:
        """Ensure sensor entity IDs are non-empty."""
        for sensor_type, entity in iter_role_entities(v):
            if not entity.strip():
                raise ValueError(f"Sensor '{sensor_type}' has empty entity_id")
        return v

    @field_validator("thermostat_entity")
    @classmethod
    def validate_thermostat_id(cls, value: str | None) -> str | None:
        """Отвергнуть пустое имя термостата.

        Пустая строка даёт пустую подписку и синхронизацию «ни с чем», а
        выглядит как настроенная комната.

        Args:
            value: Значение поля.

        Returns:
            Значение без изменений либо ``None``.
        """
        if value is not None and not value.strip():
            raise ValueError("имя термостата не может быть пустым")
        return value


class LocationConfig(StrictModel):
    """Именованная область наблюдения вне комнат (спека 016).

    Комнаты манифеста — тоже локации (``kind: room``) и описываются как раньше:
    их датчики лежат в ``RoomConfig.sensors``. Этот раздел — для зон вне комнат
    (улица, сад, теплица): у них могут быть и датчики, и приборы (уличные фонари,
    ворота и калитки, камеры, клапаны полива). Поведений у таких приборов обычно
    нет — платформа их показывает, но не управляет (решение владельца 2026-10-18).
    Привязка явная (FR-010): роль → сущность Home Assistant, без угадывания по
    именам.

    Attributes:
        id: Идентификатор локации, уникальный среди локаций и комнат.
        name: Человекочитаемое имя (идёт в снимок и в зеркало).
        kind: Вид зоны — ``outdoor``, ``garden``, ``other``. Влияет на оформление
            и умолчания, но не на логику снимка.
        sensors: Роль датчика → сущность Home Assistant.
        devices: Приборы зоны (только показ, если у них нет поведений).
    """

    id: str
    name: str
    kind: str = "other"
    parent: str | None = None
    """Место верхнего уровня: «Теплица в саду», «Грядки в саду» (B93)."""
    sensors: SensorMap = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)
    stale_after_sec: int | None = None
    """Свой порог молчания для локации. ``None`` — порог дома
    (``automation_rules.locations.stale_after_sec``). Нужен зонам с редкими
    батарейными датчиками (грядки, освещённость): для них час молчания —
    норма, а не тревога."""

    @field_validator("sensors")
    @classmethod
    def validate_sensor_ids(cls, v: SensorMap) -> SensorMap:
        """Проверить, что сущности датчиков заданы.

        Роль может ссылаться на список сущностей (несколько температур теплицы):
        проверка обязана принимать обе формы, иначе список падал на `.strip()`
        ещё до начала работы.

        Args:
            v: Привязка «роль → сущность или список сущностей».

        Returns:
            Ту же привязку.

        Raises:
            ValueError: Если у роли пустая сущность.
        """
        for sensor_type, binding in v.items():
            entities = [binding] if isinstance(binding, str) else list(binding)
            if not entities or any(not str(entity).strip() for entity in entities):
                raise ValueError(f"Sensor '{sensor_type}' has empty entity_id")
        return v
