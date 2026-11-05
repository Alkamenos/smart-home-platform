"""Factories for the platform composition root (spec 018, T057).

The container owns lifecycle and caching; creating components lives here. Each
factory receives its dependencies explicitly, so it can be tested without a
container and cannot quietly reach into global state.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from adapters.ha_adapter import HAAdapter
from adapters.mock_adapter import MockAdapter
from core.commands.middleware import ManualLockoutMiddleware
from core.deployment_manager import DeploymentManager
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.models.manifest import Manifest, role_entities


def create_state_persistence() -> Any | None:
    """Создать хранилище состояний автоматов.

    Импорт выполняется внутри функции: пакет ``core.persistence`` тянет
    ``src.core.*``, что создаёт циклический импорт с composition root.

    Returns:
        Экземпляр хранилища либо None, если хранилище создать не удалось.
    """
    try:
        from core.persistence.state_persistence import StatePersistence

        return StatePersistence()
    except (OSError, ImportError) as e:
        logger.warning(f"FSM state persistence unavailable: {e}")
        return None


def create_event_store() -> Any | None:
    """Создать журнал переходов и событий.

    Returns:
        Экземпляр журнала либо None, если журнал недоступен: отсутствие
        журнала не должно останавливать переходы автоматов (FR-003).
    """
    try:
        from core.persistence.event_store import EventStore

        return EventStore()
    except Exception as e:  # noqa: BLE001 - журнал не влияет на работу платформы
        logger.warning(f"Transition journal unavailable: {e}")
        return None


def create_external_adapter(adapter: Any) -> Any:
    """Адаптер внешней системы, если он есть.

    Args:
        adapter: Текущий адаптер платформы.

    Returns:
        Адаптер Home Assistant либо ``None`` в автономном режиме.
    """
    from adapters.ha_adapter import HomeAssistantAdapter

    return adapter if isinstance(adapter, HomeAssistantAdapter) else None


def create_mqtt_publisher(adapter: Any) -> Callable[[str, str, bool], Awaitable[bool]] | None:
    """Собрать публикатор MQTT через адаптер (зеркала, FR-008).

    ``core`` не импортирует ``adapters`` (``.ai/04_RULES.md``), поэтому
    публикация идёт вызовом сервиса через адаптер.

    Args:
        adapter: Адаптер Home Assistant либо ``None``.

    Returns:
        Функция ``(topic, payload, retain) -> bool`` либо ``None``.
    """
    if adapter is None:
        return None

    async def _publish(topic: str, payload: str, retain: bool) -> bool:
        """Опубликовать топик через Home Assistant.

        Args:
            topic: Топик MQTT.
            payload: Полезная нагрузка.
            retain: Хранить ли сообщение на брокере.

        Returns:
            True, если Home Assistant принял публикацию.
        """
        return bool(
            await adapter.call_service(
                "mqtt",
                "publish",
                "",
                data={"topic": topic, "payload": payload, "retain": retain},
            )
        )

    return _publish


def create_location_mirror(*, state: Any, rules: Any, adapter: Any) -> Any:
    """Собрать зеркало локаций в Home Assistant (спека 016, FR-008).

    Публикация идёт через адаптер (``mqtt.publish``): ``core`` не импортирует
    ``adapters``. Без адаптера зеркало собирается выключенным — снимок и
    журнал от этого не страдают (FR-009).

    Args:
        state: Служба состояния локаций.
        rules: Правила локаций из манифеста.
        adapter: Адаптер Home Assistant либо ``None``.

    Returns:
        Зеркало локаций.
    """
    from core.services.location_mirror import LocationMirror

    return LocationMirror(
        state=state,
        publish=create_mqtt_publisher(adapter),
        prefix=rules.mqtt_prefix,
        enabled=rules.mirror_enabled,
    )


def create_platform_mirror(*, rules: Any, adapter: Any) -> Any | None:
    """Собрать зеркало платформы для карточки тревог (B79).

    Args:
        rules: Правила локаций из манифеста.
        adapter: Адаптер Home Assistant либо ``None``.

    Returns:
        Зеркало платформы либо ``None``, если дом без MQTT.
    """
    publisher = create_mqtt_publisher(adapter) if rules.mirror_enabled else None
    if publisher is None:
        return None

    from core.services.platform_mirror import PlatformMirror

    return PlatformMirror(
        publish=publisher,
        prefix=rules.mqtt_prefix,
        enabled=rules.mirror_enabled,
    )


def heater_timer_entities(manifest: Manifest) -> list[str]:
    """Собрать таймеры обогревателей, объявленные в манифесте.

    Нужны адаптеру, чтобы прочитать у них единицу измерения до первого
    решения: команда в секундах вместо минут (или наоборот) выглядит снаружи
    как исправная работа — обогреватель включается и гаснет.

    Args:
        manifest: Манифест дома.

    Returns:
        Идентификаторы таймеров без повторов, в порядке манифеста.
    """
    timers: list[str] = []
    seen: set[str] = set()
    for room in manifest.rooms:
        for device in room.devices:
            for behavior in device.behaviors:
                timer = (behavior.params or {}).get("heater_timer")
                if isinstance(timer, str) and timer and timer not in seen:
                    seen.add(timer)
                    timers.append(timer)
    return timers


def heater_timer_pairs(manifest: Manifest) -> dict[str, str]:
    """Соответствие «сущность события → таймер обогревателя».

    Ключ — и сам обогреватель, и датчик температуры его комнаты: решение
    обогрева принимается по событию датчика, поэтому единица измерения
    таймера нужна именно когда приходит ``temperature_changed``.

    Args:
        manifest: Манифест дома.

    Returns:
        Словарь ``{entity_id: entity_id таймера}``.
    """
    pairs: dict[str, str] = {}
    for room in manifest.rooms:
        sensors = room.sensors or {}
        temperature = next(iter(role_entities(sensors, "temperature")), None)
        for device in room.devices:
            for behavior in device.behaviors:
                timer = (behavior.params or {}).get("heater_timer")
                if not isinstance(timer, str) or not timer:
                    continue
                pairs[device.id] = timer
                if temperature:
                    pairs[temperature] = timer
    return pairs


def bind_global_entities(adapter: Any, manifest: Manifest) -> None:
    """Передать адаптеру имена глобальных сущностей климата и вентиляции.

    Имена берутся из правил дома, значения читает адаптер при подключении.
    Роль в правилах совпадает с ролью в таблице ``GLOBAL_ENTITY_FIELDS``,
    поэтому сопоставление не выдумывает имён: неизвестная роль молча останется
    без сущности, и условие получит «данных нет».

    Args:
        adapter: Адаптер, которому передаются имена.
        manifest: Манифест дома.

    Returns:
        Ничего.
    """
    rules = manifest.automation_rules
    for field_name in (
        "setpoint_entity",
        "comfort_max_entity",
        "feature_entity",
        "ac_gate_entity",
    ):
        role = field_name.removesuffix("_entity")
        entity = getattr(rules.climate, field_name, None)
        if entity:
            adapter.climate_entities[role] = entity

    # Сезон нужен и климату, и вентиляции: это свойство дома, а не
    # климатического домена (аудит B76, A5).
    season = getattr(rules, "season_entity", None)
    if season:
        adapter.climate_entities["season"] = season

    # Термостат — свойство комнаты, а не дома (аудит B76, A6). Уставка дома
    # одна, поэтому синхронизатор берёт первый объявленный термостат; второй —
    # уже конфликт настройки, а не повод молча выбрать любой.
    thermostats: list[str] = []
    for room in manifest.rooms:
        entity = getattr(room, "thermostat_entity", None)
        if entity:
            thermostats.append(entity)
    if thermostats:
        if len(thermostats) > 1:
            logger.warning(
                "Термостатов в комнатах больше одного: "
                f"{thermostats}; синхронизация уставки идёт с {thermostats[0]}"
            )
        adapter.climate_entities["thermostat"] = thermostats[0]

    for field_name in (
        "feature_entity",
        "enable_entity",
        "airing_entity",
        "exhaust_entity",
        "outside_temp_entity",
    ):
        entity = getattr(rules.ventilation, field_name, None)
        if not entity:
            continue
        # Роль `feature` занята климатом, поэтому у вентиляции она своя.
        role = field_name.removesuffix("_entity")
        if role == "feature":
            role = "ventilation_feature"
        adapter.ventilation_entities[role] = entity

    # Флаги штор (спека 015). Роли совпадают с ключами GLOBAL_ENTITY_FIELDS.
    for field_name in (
        "feature_entity",
        "my_doma_entity",
        "sobaki_doma_entity",
        "night_close_entity",
        "emergency_entity",
    ):
        entity = getattr(rules.cover, field_name, None)
        if not entity:
            continue
        # Роль `feature` занята климатом — у штор она своя.
        role = field_name.removesuffix("_entity")
        if role == "feature":
            role = "covers_feature"
        adapter.cover_entities[role] = entity

    # Глобальная цветовая температура света: день/ночь — границы, current —
    # значение, которое читают действия включения и обновляет служба света.
    for field_name in (
        "color_temp_day_entity",
        "color_temp_night_entity",
        "color_temp_current_entity",
    ):
        entity = getattr(rules.lighting, field_name, None)
        if entity:
            adapter.lighting_entities[field_name.removesuffix("_entity")] = entity

    # Разрешение на автоматическое включение планового света. Флаг живёт на
    # уровне дома: владелец решает, можно ли автоматике включать основное
    # уличное освещение по закату.
    scheduled_feature = getattr(rules, "scheduled_light_feature_entity", None)
    if scheduled_feature:
        adapter.lighting_entities["scheduled_feature"] = scheduled_feature

    logger.info(
        f"Глобальные сущности: климат {adapter.climate_entities}, "
        f"вентиляция {adapter.ventilation_entities}, свет {adapter.lighting_entities}, "
        f"шторы {adapter.cover_entities}"
    )


def create_adapter(
    *,
    engine: FSMEngine,
    event_router: EventRouter,
    deployment: DeploymentManager,
    middleware: ManualLockoutMiddleware,
    manifest: Manifest,
    heater_timers: list[str],
    heater_timer_pairs: dict[str, str],
    on_sleep_started: Callable[[], Awaitable[None]],
    on_sunset: Callable[[], Awaitable[None]],
    on_sunrise: Callable[[], Awaitable[None]],
) -> HAAdapter | MockAdapter:
    """Создать адаптер Home Assistant или автономную заглушку.

    Args:
        engine: Движок автоматов.
        event_router: Маршрутизатор событий.
        deployment: Менеджер режима развёртывания.
        middleware: Посредник ручной блокировки.
        manifest: Манифест дома.
        heater_timers: Таймеры обогревателей.
        heater_timer_pairs: Пары «сущность → таймер».
        on_sleep_started: Колбэк включения модификатора сна.
        on_sunset: Колбэк заката.
        on_sunrise: Колбэк рассвета.

    Returns:
        Настроенный адаптер.
    """
    ws_url = os.environ.get("HA_WEBSOCKET_URL", "ws://localhost:8123/api/websocket")
    ha_token = os.environ.get("HA_TOKEN")

    if not ha_token:
        mock = MockAdapter(engine=engine)
        mock.set_event_router(event_router)
        return mock

    adapter = HAAdapter(
        mode="websocket",
        engine=engine,
        event_router=event_router,
        ws_url=ws_url,
        token=ha_token,
        deployment=deployment,
        # Ручная блокировка обязана слышать живые события дома: адаптер
        # вызывает record_manual_control при user_id в конверте события.
        manual_lockout_middleware=middleware,
    )
    # Манифест отдаётся адаптеру для фильтра подписки: без него HA присылает
    # все сущности дома, и платформа отбивает каждое событие лишней сущности.
    adapter._manifest = manifest
    # Таймеры обогревателей нужны адаптеру, чтобы прочитать у них единицу
    # измерения (боевой дефект 2026-10-11: таймер измеряется в секундах, а
    # команда уходила минутами, и обогрев молчал сутки).
    if heater_timers:
        adapter.heater_timers = list(heater_timers)
        adapter.heater_timer_of = heater_timer_pairs

    # Модификатор «мы спим» — сущность Home Assistant, которой владелец
    # управляет сам. Платформа читает состояние и по нему решает, можно ли
    # включать яркий свет; без имени сущности условие его просто не найдёт.
    sleep_modifier = manifest.automation_rules.sleep_modifier
    if sleep_modifier:
        adapter.sleep_modifier_entity = sleep_modifier
        adapter.on_sleep_started = on_sleep_started
        logger.info(
            f"Модификатор «мы спим»: {sleep_modifier} — состояние "
            "владелец задаёт сам, платформа только читает"
        )
    # Закат и рассвет нужны декоративному свету независимо от модификатора,
    # поэтому подключаются всегда.
    adapter.on_sunset = on_sunset
    adapter.on_sunrise = on_sunrise

    # Уставка, сезон, потолок комфорта и выключалка вентиляции — те же
    # глобальные признаки, только климата и вентиляции. Без них условия
    # получают «данных нет»: до 2026-10-10 писателя не существовало, и обогрев
    # не включался ни в одной комнате.
    bind_global_entities(adapter, manifest)
    return adapter
