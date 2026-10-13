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
from pydantic import BaseModel, Field, field_validator


class InstanceConfig(BaseModel):
    """Platform instance metadata."""

    id: str
    name: str
    owner: str = ""
    created_at: str = ""


class BehaviorConfig(BaseModel):
    """Behavior template with priority and params."""

    template: str
    priority: int = 10
    params: dict[str, Any] = Field(default_factory=dict)


class DeviceConfig(BaseModel):
    """Device as an actuator inside a room."""

    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = Field(default_factory=list)


class RoomConfig(BaseModel):
    """Room: container for sensors and devices.

    Sensors describe room state (inputs).
    Devices are actuators that react to processed events (outputs).
    Same sensor entity_id can appear in multiple rooms.
    """

    id: str
    name: str
    sensors: dict[str, str] = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)

    @field_validator("sensors")
    @classmethod
    def validate_sensor_ids(cls, v: dict[str, str]) -> dict[str, str]:
        """Ensure sensor entity IDs are non-empty."""
        for sensor_type, entity_id in v.items():
            if not entity_id.strip():
                raise ValueError(f"Sensor '{sensor_type}' has empty entity_id")
        return v


class LocationConfig(BaseModel):
    """Именованная область наблюдения вне комнат (спека 016).

    Комнаты манифеста — тоже локации (``kind: room``) и описываются как раньше:
    их датчики лежат в ``RoomConfig.sensors``. Этот раздел — для зон вне комнат
    (улица, грядки): у них нет устройств, только датчики. Привязка явная
    (FR-010): роль → сущность Home Assistant, без угадывания по именам.

    Attributes:
        id: Идентификатор локации, уникальный среди локаций и комнат.
        name: Человекочитаемое имя (идёт в снимок и в зеркало).
        kind: Вид зоны — ``outdoor``, ``garden``, ``other``. Влияет на оформление
            и умолчания, но не на логику снимка.
        sensors: Роль датчика → сущность Home Assistant.
    """

    id: str
    name: str
    kind: str = "other"
    sensors: dict[str, str] = Field(default_factory=dict)
    stale_after_sec: int | None = None
    """Свой порог молчания для локации. ``None`` — порог дома
    (``automation_rules.locations.stale_after_sec``). Нужен зонам с редкими
    батарейными датчиками (грядки, освещённость): для них час молчания —
    норма, а не тревога."""

    @field_validator("sensors")
    @classmethod
    def validate_sensor_ids(cls, v: dict[str, str]) -> dict[str, str]:
        """Проверить, что сущности датчиков заданы.

        Args:
            v: Привязка «роль → сущность».

        Returns:
            Ту же привязку.

        Raises:
            ValueError: Если у роли пустая сущность.
        """
        for sensor_type, entity_id in v.items():
            if not entity_id.strip():
                raise ValueError(f"Sensor '{sensor_type}' has empty entity_id")
        return v


class AutomationDomainRules(BaseModel):
    """Domain-specific automation rules.

    Поля ночного света объявлены здесь, а не в коде: окно тишины и список
    комнат, где ночью свет включить можно, — это решение владельца дома, а не
    свойство движка. Значения попадают в параметры поведения и читаются
    условием ``may_turn_on``.
    """

    motion_enabled: bool = True
    schedule_enabled: bool = True
    manual_lockout_min: int | None = None
    safety_lockout_enabled: bool = False
    away_mode_enabled: bool = False
    humidity_based: bool = False
    quiet_from: str | None = None
    """С часа ночью движение не включает свет (``HH:MM``)."""
    quiet_to: str | None = None
    """До этого часа включительно — тоже ночь (``HH:MM``)."""
    night_motion_rooms: list[str] | None = None
    """Комнаты, где ночью свет по движению включается (санузел, кухня)."""
    always_on_motion_rooms: list[str] | None = None
    """Комнаты без окон, где свет по движению включается всегда (санузел, контейнер).

    Солнце освещает только комнаты с окнами: в комнате без окна днём ровно так
    же темно, как ночью. Для таких комнат условие «светло — не включаем» не
    работает, и движение гасло вхолостую (боевой дефект 2026-10-10: датчик в
    санузле срабатывал, а свет не включался, отказ ``daylight``).

    Модификатор «мы спим» остаётся выше этого списка: спящим яркий свет не нужен
    ни в одной комнате, включая санузел."""
    night_off_at: str | None = None
    """Час принудительного выключения света, заданного автоматикой."""
    sleep_modifier: str | None = None
    """Сущность Home Assistant «мы спим» (например, ``input_boolean.sleep_mode``).

    Модификатор включает и выключает владелец сам — автоматизацией HA по
    своему расписанию (например, 23:00–07:00), платформа только читает
    состояние. Пока модификатор включён, яркий свет не включается нигде —
    иначе ночной свет сбивает циркадные ритмы (требование владельца
    2026-10-09). Сущности нет или её состояние неизвестно — модификатора
    нет, и решает солнце/окно тишины, а не «спим»."""
    morning_at: str | None = None
    """Час снятия ночного режима."""
    hold_sec: int | None = None
    """Сколько горит свет после последнего движения."""
    max_on_sec: int | None = None
    """Потолок горения без свежих триггеров."""
    battery_watch_entities: list[str] | None = None
    """Батарейки, за которыми платформа следит.

    Само наблюдение узкое: по умолчанию берутся батарейки датчиков, описанных в
    манифесте, то есть тех, по которым принимаются решения. Список задан здесь
    для датчиков вне манифеста — например, уличного датчика на террасе: он не
    участвует в автоматике, но его батарейку всё равно надо менять, а узнать
    заранее можно только отсюда."""

    # ─── Климат (спека 014) ───
    # Уставка и прочие признаки живут в Home Assistant: владелец меняет их сам,
    # и второе место, где ту же логику можно сломать, только вредит. Платформа
    # читает — и потому обязана знать, откуда читать.
    setpoint_entity: str | None = None
    thermostat_entity: str | None = None
    """Основной термостат дома (`climate.*`), задающий уставку.

    Требование владельца 2026-10-12: изменение цели термостата должно менять
    уставку дома, а изменение уставки — писаться в термостат. У климат-сущности
    цель живёт в атрибуте `temperature`, а не в состоянии: состояние климата —
    это режим (heat/off), и читать его как уставку нельзя.
    """
    """Сущность целевой температуры (например ``input_number.temperatura``)."""
    comfort_max_entity: str | None = None
    """Сущность потолка комфорта, выше которого в комнате жарко."""
    season_entity: str | None = None
    """Сущность сезона: зимой кондиционер включать нельзя."""
    feature_entity: str | None = None
    """Признак «фича включена»; при выключенном платформа только наблюдает."""
    ac_gate_entity: str | None = None
    """Разрешение владельца на кондиционер."""
    setpoint_min: float = 5.0
    """Нижняя граница допустимой уставки."""
    setpoint_max: float = 30.0
    """Верхняя граница допустимой уставки."""

    # ─── Вентиляция (спека 014) ───
    enable_entity: str | None = None
    """Выключалка вентиляции владельца; ``off`` сильнее любого правила."""
    airing_entity: str | None = None
    """Проветривание: максимальный приток на заданный срок."""
    exhaust_entity: str | None = None
    """Режим вытяжки по отдельной кнопке."""
    outside_temp_entity: str | None = None
    """Уличная температура: по разнице с комнатой выбирается режим."""

    # ─── Шторы (спека 015) ───
    # Флаги дома живут в Home Assistant (владелец правит их сам), платформа
    # только читает. Ими решается, закрывать ли шторы: спим ли, кто-то ли дома,
    # дома ли собаки, разрешено ли закрывать ночью.
    my_doma_entity: str | None = None
    """Признак «кто-то дома» (``input_boolean.my_doma``).

    Пока он включён, штора над дверью не закрывается из соображений пожарной
    безопасности — закрытая дверь мешает выходу. Выключенный признак отменяет
    логику «мы спим»: шторы решаются по отсутствию людей, а не по сну.
    """
    sobaki_doma_entity: str | None = None
    """Признак «дома собаки» (``input_boolean.sobaki_doma``).

    Вместе с ``my_doma = false`` он отделяет «уехали с собаками» от «уехали без
    собак»: во втором случае закрываются все шторы (включая дверь), в первом —
    только спальня и кабинет.
    """
    night_close_entity: str | None = None
    """Разрешение закрывать шторы ночью (``input_boolean.zakryvat_shtory_nochiu``).

    Включено — спящий дом закрывает шторы; выключено — не закрывает, хотя
    «мы спим». Это ручка владельца: летом шторы ночью закрывать не нужно.
    """
    emergency_entity: str | None = None
    """Аварийный флаг (``input_boolean.covers_emergency_open``).

    Включён — все шторы открываются, игнорируя остальные правила. Нужен на
    случай, когда закрытые шторы мешают (пожар, эвакуация).
    """

    @field_validator(
        "setpoint_entity",
        "comfort_max_entity",
        "season_entity",
        "feature_entity",
        "ac_gate_entity",
        "enable_entity",
        "airing_entity",
        "exhaust_entity",
        "outside_temp_entity",
        "my_doma_entity",
        "sobaki_doma_entity",
        "night_close_entity",
        "emergency_entity",
    )
    @classmethod
    def _reject_blank_entity(cls, value: str | None) -> str | None:
        """Отвергнуть пустую сущность.

        Пустая строка даёт пустую подписку, и отказ выглядит как штатная
        работа: «настроил, а не работает» без единого сообщения. Ошибка
        загрузки манифеста честнее — она указывает строку.

        Args:
            value: Значение поля.

        Returns:
            Значение без изменений либо ``None``.
        """
        if value is not None and not value.strip():
            raise ValueError("имя сущности не может быть пустым")
        return value

    @field_validator("manual_lockout_min")
    @classmethod
    def _reject_negative_lockout(cls, value: int | None) -> int | None:
        """Отвергнуть отрицательный срок блокировки.

        Args:
            value: Значение поля.

        Returns:
            Значение без изменений либо ``None``.
        """
        if value is not None and value < 0:
            raise ValueError("срок ручной блокировки не может быть отрицательным")
        return value

    @field_validator("setpoint_max")
    @classmethod
    def _check_setpoint_range(cls, value: float, info: Any) -> float:
        """Проверить, что границы уставки заданы в правильном порядке.

        Обратный порядок означал бы, что любая уставка «вне диапазона» и
        отказ по ней приходят в запутанном виде, а владелец не понимает, что
        исправлять.

        Args:
            value: Значение поля.
            info: Контекст валидации с остальными полями.

        Returns:
            Значение без изменений.
        """
        lower = (info.data or {}).get("setpoint_min")
        if lower is not None and value <= lower:
            raise ValueError(
                f"верхняя граница уставки ({value}) должна быть больше нижней ({lower})"
            )
        return value


class LocationRules(BaseModel):
    """Правила наблюдения за локациями (спека 016).

    Порог молчания и окно присутствия — параметры дома, а не константы кода:
    датчики дома разные, и «молчит» означает разное время для сетевого датчика
    температуры и для батарейного датчика почвы.
    """

    stale_after_sec: int = 3600
    """Молчание дольше этого времени — датчик помечается ``stale``."""

    presence_window_sec: int = 600
    """Движение считает локацию занятой это время после последнего срабатывания."""


class AutomationRules(BaseModel):
    """Global automation rules and domain-specific overrides."""

    global_manual_lockout_min: int = 60
    time_zone: str | None = None
    """Часовой пояс дома. Обязателен для правил «светло ли сейчас»: дом живёт
    в своём поясе, а контейнер — в UTC, и без этого окно дня смещается на
    несколько часов."""
    lighting: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    climate: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    ventilation: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    cover: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    """Шторы дома (спека 015): общие флаги и правила закрытия."""
    locations: LocationRules = Field(default_factory=LocationRules)
    """Наблюдение за локациями (спека 016): порог молчания, окно присутствия."""


class Dashboard(BaseModel):
    """Dashboard configuration for Lovelace generation."""

    title: str = ""
    rooms: list[str] = Field(default_factory=list)
    show_sensors: bool = True
    show_devices: bool = True


class Manifest(BaseModel):
    """Root manifest model for room-based architecture."""

    instance: InstanceConfig
    version: int = 1
    rooms: list[RoomConfig] = Field(default_factory=list)
    #: Особые зоны наблюдения вне комнат (спека 016): улица, грядки. Комнаты
    #: тоже локации и описываются как раньше — в ``rooms``.
    locations: list[LocationConfig] = Field(default_factory=list)
    automation_rules: AutomationRules = Field(default_factory=AutomationRules)
    dashboard: Dashboard = Field(default_factory=Dashboard)

    @property
    def devices(self) -> list[DeviceConfig]:
        """Flat list of all devices across all rooms."""
        return [device for room in self.rooms for device in room.devices]

    @property
    def zones(self) -> list[RoomConfig]:
        """Alias for rooms (backward compat with old Zone model)."""
        return self.rooms

    @property
    def all_devices(self) -> list[tuple[str, DeviceConfig]]:
        """Flat list of (room_id, device) for iteration."""
        return [(room.id, device) for room in self.rooms for device in room.devices]

    @property
    def all_device_ids(self) -> list[str]:
        """Flat list of all device IDs."""
        return [device.id for _, device in self.all_devices]

    def get_room_for_device(self, device_id: str) -> RoomConfig | None:
        """Find the room containing a device."""
        for room in self.rooms:
            if any(d.id == device_id for d in room.devices):
                return room
        return None

    def get_device(self, device_id: str) -> DeviceConfig | None:
        """Find a device by ID across all rooms."""
        for _, device in self.all_devices:
            if device.id == device_id:
                return device
        return None

    def get_sensors_for_device(self, device_id: str) -> dict[str, str]:
        """Get sensors available for a device (from its room)."""
        room = self.get_room_for_device(device_id)
        return room.sensors if room else {}


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
        raise FileNotFoundError(f"Manifest not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return Manifest.model_validate(data)


# Zone в новой архитектуре = Room
class Zone(BaseModel):
    """Zone is now an alias for RoomConfig with optional floor."""

    id: str
    name: str
    floor: int = 1
    sensors: dict[str, str] = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)


InstanceInfo = InstanceConfig
