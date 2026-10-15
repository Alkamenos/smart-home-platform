"""Pydantic models for Smart Home Manifest that match the real structure."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from core.models.manifest import LocationConfig, LocationRules, SensorMap


class InstanceConfig(BaseModel):
    """Instance configuration model."""

    id: str = Field(..., description="Unique instance identifier")
    name: str = Field(..., description="Human-readable instance name")
    owner: str = Field(default="Unknown", description="Instance owner")
    created_at: str = Field(default="", description="Creation timestamp")


class BehaviorConfig(BaseModel):
    """Behavior configuration for a device."""

    template: str = Field(..., description="Template name")
    priority: int = Field(..., description="Priority level")
    params: dict[str, Any] = Field(default_factory=dict, description="Behavior parameters")


class DeviceConfig(BaseModel):
    """Device configuration within a room."""

    id: str = Field(..., description="Device entity ID")
    type: str = Field(..., description="Device type")
    name: str = Field(default="", description="Human-readable device name")
    behaviors: list[BehaviorConfig] = Field(default_factory=list, description="Device behaviors")


class RoomConfig(BaseModel):
    """Room configuration model."""

    id: str = Field(..., description="Room identifier")
    name: str = Field(..., description="Human-readable room name")
    sensors: SensorMap = Field(
        default_factory=dict, description="Room sensors: роль → сущность или список"
    )
    devices: list[DeviceConfig] = Field(default_factory=list, description="Room devices")

    model_config = {"extra": "allow"}


class AutomationDomainRules(BaseModel):
    """Automation rules for a specific domain."""

    motion_enabled: bool = Field(default=True, description="Enable motion-based automation")
    schedule_enabled: bool = Field(default=True, description="Enable schedule-based automation")
    manual_lockout_min: int | None = Field(
        default=None,
        description=(
            "Minutes to block automation after manual control. "
            "Совпадает с ядерной моделью: None означает «настройка не задана»"
        ),
    )
    safety_lockout_enabled: bool = Field(default=False, description="Enable safety lockout")
    away_mode_enabled: bool = Field(default=False, description="Enable away mode")
    humidity_based: bool = Field(default=False, description="Enable humidity-based automation")
    # Поля домена расширяются ядром (ночное окно, комнаты, шторы): без разрешения
    # «лишних» полей правка манифеста через интерфейс вычёркивала бы их.
    model_config = {"extra": "allow"}


class AutomationClimateRules(AutomationDomainRules):
    """Правила климата: к общим полям домена добавляются поля кондиционера.

    Отдельный класс, а не поля в общем: иначе «кондиционер» показывался бы в блоке
    освещения (замечание владельца 2026-10-15), а правка правил света предлагала бы
    настраивать кондиционер.
    """

    ac_min_outside_temp: float = Field(
        default=5.0,
        description=(
            "Ниже этой уличной температуры кондиционер включать нельзя: дренаж "
            "замёрзнет (требование владельца 2026-10-15). Поле объявлено и здесь: "
            "иначе правка манифеста через интерфейс вычеркнула бы его"
        ),
    )
    ac_entities: list[str] = Field(
        default_factory=list,
        description=(
            "Кондиционеры под защитой платформы: зимой и без разрешения владельца "
            "охлаждать нельзя (требование владельца 2026-10-15). Поле объявлено и "
            "здесь: иначе правка манифеста через интерфейс вычеркнула бы его"
        ),
    )
    ac_gate_entity: str | None = Field(
        default=None,
        description=(
            "Необязательный явный запрет владельца на кондиционер. Нет гейта — "
            "охлаждение им не запрещается. Поле объявлено и здесь: иначе правка "
            "манифеста через интерфейс вычеркнула бы его"
        ),
    )


class AutomationRules(BaseModel):
    """Global automation rules.

    Поля повторяют каноническую модель ядра: пропущенное поле при сохранении
    манифеста через интерфейс молча терялось бы — так уже произошло с
    ``time_zone``, ``cover`` и ``locations``. ``extra: allow`` страхует от
    повторов при добавлении новых разделов в ядре.
    """

    global_manual_lockout_min: int = Field(default=60, description="Global manual lockout minutes")
    manual_command_sources: list[str] = Field(
        default_factory=list,
        description=(
            "Дополнительные источники команд, которые считать ручными (например, "
            "telegram). Поле объявлено и здесь: иначе правка манифеста через "
            "интерфейс вычеркнула бы его (аудит 2026-10-16, К-10)"
        ),
    )
    time_zone: str | None = Field(default=None, description="Часовой пояс дома")
    lighting: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    climate: AutomationClimateRules = Field(default_factory=AutomationClimateRules)
    ventilation: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    cover: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    locations: LocationRules = Field(
        default_factory=LocationRules, description="Правила наблюдения за локациями (спека 016)"
    )

    @field_validator("climate", mode="before")
    @classmethod
    def _accept_generic_domain(cls, value: Any) -> Any:
        """Принять и общие правила домена: поля кондиционера добавляются к ним.

        Args:
            value: Значение поля ``climate``.

        Returns:
            Правила климата либо исходное значение.
        """
        if isinstance(value, AutomationDomainRules) and not isinstance(
            value, AutomationClimateRules
        ):
            return AutomationClimateRules(**value.model_dump())
        return value

    model_config = {"extra": "allow"}


class DashboardConfig(BaseModel):
    """Dashboard configuration."""

    title: str = Field(default="", description="Dashboard title")
    rooms: list[str] = Field(default_factory=list, description="Rooms to show on dashboard")
    show_sensors: bool = Field(default=True, description="Show sensors on dashboard")
    show_devices: bool = Field(default=True, description="Show devices on dashboard")


class ManifestModel(BaseModel):
    """Main manifest configuration model matching real YAML structure."""

    instance: InstanceConfig = Field(..., description="Instance configuration")
    version: int = Field(default=1, description="Manifest schema version")
    rooms: list[RoomConfig] = Field(default_factory=list, description="Rooms in the smart home")
    locations: list[LocationConfig] = Field(
        default_factory=list,
        description="Особые зоны наблюдения (улица, грядки) — спека 016",
    )
    battery_types: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Тип батарейки по сущности (sensor.…_battery → CR2032). Поле объявлено и "
            "здесь: иначе правка манифеста через интерфейс вычеркнула бы его"
        ),
    )
    automation_rules: AutomationRules = Field(
        default_factory=AutomationRules, description="Automation rules"
    )
    dashboard: DashboardConfig = Field(
        default_factory=DashboardConfig, description="Dashboard configuration"
    )

    model_config = {"extra": "allow"}


class FSMStateView(BaseModel):
    """Состояние автомата в ответах интерфейса.

    Отличается от внутреннего состояния движка: ``since`` — настенное время в
    формате ISO-8601, а не монотонные часы цикла событий, а внутренний контекст
    состояния наружу не отдаётся (FR-017, R-04).
    """

    fsm_id: str = Field(..., description="Идентификатор автомата {устройство}_{шаблон}_{приоритет}")
    device_id: str = Field(..., description="Фактическое устройство автомата")
    behavior: str = Field(default="", description="Имя шаблона поведения")
    state: str = Field(default="", description="Текущее состояние автомата")
    since: str | None = Field(
        default=None, description="Время последнего перехода в формате ISO-8601"
    )
    automated: bool = Field(default=True, description="Есть ли у устройства автоматика")


class AutomationInfo(BaseModel):
    """Наличие автоматики у устройства.

    Отличает «автоматика не настроена» от «сервис недоступен»: устройство без
    автоматики получает явную отметку, а не пустое значение (FR-019).
    """

    configured: bool = Field(..., description="Настроена ли автоматика")
    fsm_ids: list[str] = Field(default_factory=list, description="Идентификаторы автоматов")
    reason: str | None = Field(
        default=None, description="Причина отсутствия автоматики, если не настроена"
    )


def build_fsm_state_view(
    engine: Any,
    fsm_id: str,
    device_id: str | None,
    to_state: str | None,
    state: Any,
) -> FSMStateView:
    """Собрать представление состояния автомата.

    Args:
        engine: Движок состояний — источник состояния и времени перехода.
        fsm_id: Идентификатор автомата.
        device_id: Устройство из описания автомата; при отсутствии используется
            идентификатор автомата.
        to_state: Новое состояние из описания автомата; используется, когда у
            движка нет состояния для автомата.
        state: Состояние движка либо None.

    Returns:
        Представление состояния для ответа интерфейса.
    """
    from core.events.fsm_events import split_fsm_id

    _, behavior = split_fsm_id(fsm_id)
    current_state = getattr(state, "current_state", None) or to_state or ""
    get_time = getattr(engine, "get_last_transition_time", None)
    since = get_time(fsm_id) if callable(get_time) else None

    return FSMStateView(
        fsm_id=fsm_id,
        device_id=device_id or fsm_id,
        behavior=behavior,
        state=current_state,
        since=since,
        automated=bool(behavior),
    )


def build_all_fsm_state_views(engine: Any, allowed_devices: set[str] | None) -> list[FSMStateView]:
    """Собрать представления состояний всех автоматов доступных устройств.

    Args:
        engine: Движок состояний.
        allowed_devices: Устройства, доступные пользователю. ``None`` означает
            отсутствие фильтрации (администратор или недоступный сервис
            доступа), а пустое множество — что у пользователя нет доступных
            устройств, поэтому результат пуст (FR-038).

    Returns:
        Список представлений в порядке идентификаторов автоматов.
    """
    if allowed_devices is not None and not allowed_devices:
        return []

    states = engine.get_all_states()
    definitions = getattr(engine, "_definitions", {})

    views: list[FSMStateView] = []
    for fsm_id in sorted(set(states) | set(definitions)):
        definition = definitions.get(fsm_id)
        device_id = getattr(definition, "target_device_id", None)
        if allowed_devices is not None and device_id and device_id not in allowed_devices:
            continue
        views.append(
            build_fsm_state_view(
                engine,
                fsm_id,
                device_id,
                getattr(definition, "initial_state", None),
                states.get(fsm_id),
            )
        )
    return views


def build_automation_info(fsm_ids: list[str]) -> AutomationInfo:
    """Собрать сведения об автоматике устройства.

    Args:
        fsm_ids: Идентификаторы автоматов устройства.

    Returns:
        Настроена ли автоматика и какими автоматами.
    """
    if fsm_ids:
        return AutomationInfo(configured=True, fsm_ids=fsm_ids)
    return AutomationInfo(configured=False, reason="no_automation")
