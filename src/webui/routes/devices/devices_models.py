"""Схемы запросов и ответов раздела устройств (BACKLOG B80).

Вынесены из `devices.py`: у маршрутов и у схем разные причины меняться, а рядом
они мешали читать друг друга.
"""

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from webui.models import AutomationInfo, FSMStateView


logger = logging.getLogger(__name__)


class DeviceResponse(BaseModel):
    """Ответ с информацией об устройстве."""

    id: str
    name: str
    display_name: str | None = None
    device_type: str
    status: str
    state: dict
    source_id: str
    ha_entity_id: str
    ha_area_id: str | None = None
    description: str | None = None
    location: str | None = None
    tags: list[str] | None = None
    created_at: str
    updated_at: str
    fsm: list[FSMStateView] = Field(default_factory=list, description="States of device FSMs")
    behaviors: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Поведения устройства из манифеста: шаблон, приоритет и параметры. "
            "Форма правки предзаполняется из этого поля, поэтому без него "
            "пользователь увидел бы пустые параметры и стёр бы их"
        ),
    )
    automation: AutomationInfo = Field(
        default_factory=lambda: AutomationInfo(configured=False, reason="no_automation"),
        description="Automation availability for the device",
    )
    decision: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Последнее решение автоматики: исход, причина человеческим языком и "
            "время. Нужно интерфейсу, чтобы ответить «почему так» без журнала"
        ),
    )


class UpdateDeviceConfigRequest(BaseModel):
    """Запрос на обновление конфигурации устройства."""

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    location: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = Field(None)


class CommandRequest(BaseModel):
    """Единый запрос выполнения команды (T054 + совместимость).

    Принимает три формата (валидатор — хотя бы один идентификатор команды):
    - T054: ``name`` + обязательные ``parameters``;
    - name-алиас: ``command_name`` (параметры необязательны);
    - сервисный: ``service`` + ``data``.
    """

    name: str | None = Field(
        default=None, min_length=1, max_length=255, description="Имя команды T054"
    )
    command_name: str | None = Field(
        None, min_length=1, max_length=255, description="Имя команды (алиас)"
    )
    parameters: dict | None = Field(
        default=None, description="Параметры команды (обязательны с name)"
    )
    service: str | None = Field(default=None, description="Сервис HA (domain.service)")
    data: dict | None = Field(default=None, description="Данные сервиса")

    @model_validator(mode="after")
    def _validate_command_identity(self) -> "CommandRequest":
        """Требует хотя бы один идентификатор команды (contracts §3).

        Returns:
            Саму модель при валидном наборе полей.

        Raises:
            ValueError: если идентификатор не указан или формат неполон.
        """
        if self.command_name:
            return self
        if self.service:
            return self
        if self.name:
            if self.parameters is None:
                raise ValueError("Поле 'parameters' обязательно при использовании формата 'name'")
            return self
        raise ValueError("Укажите 'command_name', 'name' (с 'parameters') или 'service'")


class CommandResponse(BaseModel):
    """Ответ при выполнении команды."""

    id: str = Field(description="ID выполненной команды")
    device_id: str = Field(description="ID устройства")
    command_name: str = Field(description="Имя команды")
    status: str = Field(description="Статус: pending, executing, success, failed")
    created_at: str = Field(description="Время создания")
    completed_at: str | None = None
    result: dict | None = None
    error: str | None = None
    automation_synced: bool = Field(
        default=False,
        description=(
            "Отражена ли команда в состоянии автомата. False означает, что команда "
            "ушла прямо в Home Assistant: в шаблоне нет ручного перехода, и автомат "
            "о состоянии устройства не знает (Known Issue #69)."
        ),
    )


class DeviceEventResponse(BaseModel):
    """Событие устройства."""

    id: str = Field(description="ID события")
    device_id: str = Field(description="ID устройства")
    event_type: str = Field(
        description="Тип события: state_changed, config_changed, command_executed"
    )
    timestamp: str = Field(description="Время события")
    data: dict = Field(description="Данные события")


class BehaviorSelection(BaseModel):
    """Поведение устройства, выбранное пользователем."""

    template: str = Field(description="Шаблон автоматизации")
    priority: int = Field(default=10, ge=1, description="Приоритет: меньше — выше")
    params: dict[str, Any] = Field(default_factory=dict, description="Параметры шаблона")


class DeviceSelection(BaseModel):
    """Выбранное устройство для добавления."""

    device_entity_id: str = Field(description="Entity ID в Home Assistant")
    device_type: str | None = Field(
        None, description="Тип устройства; по умолчанию — домен из entity_id"
    )
    name: str | None = Field(default=None, description="Имя устройства; по умолчанию — entity_id")
    target_room: str | None = Field(default=None, description="Целевая комната для устройства")
    behavior_template: str | None = Field(
        default=None, description="Рекомендуемый шаблон поведения"
    )
    ha_area_id: str | None = Field(default=None, description="ID области в HA")
    behaviors: list[BehaviorSelection] | None = Field(
        None, description="Поведения устройства; при отсутствии — рекомендованный шаблон"
    )


class ApplyDevicesRequest(BaseModel):
    """Запрос на добавление выбранных устройств."""

    source_id: UUID = Field(description="ID источника Home Assistant")
    selections: list[DeviceSelection] = Field(description="Список выбранных устройств")
    dry_run: bool = Field(default=False, description="Если True, только проверяет, не добавляет")


class FailedDevice(BaseModel):
    """Устройство, которое не удалось применить."""

    ha_entity_id: str = Field(description="Entity ID устройства")
    reason: str = Field(description="Причина отказа")


class ApplyDevicesResponse(BaseModel):
    """Ответ при добавлении устройств (contracts/device-lifecycle-api.md)."""

    success: bool = Field(description="Ошибок не было")
    devices_count: int = Field(description="Количество применённых устройств")
    devices: list[DeviceResponse] = Field(
        default_factory=list, description="Применённые устройства"
    )
    devices_added: int = Field(default=0, description="Добавлено новых устройств")
    devices_updated: int = Field(default=0, description="Обновлено существующих")
    failed: int = Field(default=0, description="Количество неудачных применений")
    failed_devices: list[FailedDevice] = Field(
        default_factory=list, description="Устройства, которые не удалось применить"
    )
    dry_run: bool = Field(default=False, description="Был ли это тестовый запуск")
    would_add: int | None = Field(default=None, description="Сколько устройств было бы добавлено")
    errors: list[str] | None = Field(default=None, description="Человекочитаемые ошибки")


class BehaviorsUpdateRequest(BaseModel):
    """Запрос замены поведений устройства."""

    behaviors: list[BehaviorSelection] = Field(
        description="Новый список поведений; пустой список снимает все поведения"
    )
    room_id: str | None = Field(
        None,
        description=(
            "Комната устройства. Обычно не нужна: комната берётся из манифеста по "
            "entity_id. Указывается, когда устройства в манифесте нет"
        ),
    )


class BehaviorsUpdateResponse(BaseModel):
    """Ответ на правку поведений."""

    device_id: str = Field(description="ID устройства")
    behaviors: list[dict] = Field(description="Поведения после сохранения")
    inert_params: list[str] = Field(
        default_factory=list,
        description="Параметры, которые не влияют на поведение (Known Issue #71)",
    )
