"""
Dependency Injection Container for Smart Home Platform.

This module provides a lightweight DI container with lazy initialization
for better modularity and testability.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from datetime import time as dt_time
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from adapters.ha_adapter import HAAdapter
from adapters.mock_adapter import MockAdapter
from core.action_handlers import register_all_actions
from core.commands.dispatcher import CommandDispatcher, HAAdapterProtocol
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.deployment_manager import DeploymentManager
from core.events.event_bus import EventBus
from core.events.event_router import EventRouter
from core.events.fsm_events import EVENT_PLATFORM_STARTED
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import register_all_guards
from core.models.manifest import (
    Manifest,
    all_sensor_entities,
    load_manifest,
    role_entities,
)
from core.persistence.manual_control_store import ManualControlStore
from core.registry import Registry


@dataclass
class PlatformContext:
    """
    Container for all platform components.

    Attributes:
        manifest: Loaded manifest with automation rules.
        event_bus: EventBus for publishing/subscribing to events.
        fsm: FSMEngine for state machine management.
        control_tracker: ControlTracker for tracking manual interventions.
        adapter: HAAdapter or MockAdapter for calling services.
        dispatcher: CommandDispatcher with middleware chain.
        event_router: EventRouter for routing sensor events to FSMs.
        fsm_bridge: Bridge delivering FSM transitions to persistence, Home
            Assistant mirror and live updates.
    """

    manifest: Manifest
    event_bus: EventBus
    fsm: FSMEngine
    control_tracker: ControlTracker
    adapter: Any  # HAAdapter or MockAdapter
    dispatcher: CommandDispatcher
    event_router: EventRouter
    fsm_bridge: Any = None
    watchdog: Any = None
    day_cycle: Any = None
    deco_watcher: Any = None
    #: Защита кондиционера: гасит охлаждение, недопустимое по правилам дома
    #: (зима, запрет владельца) — требование владельца 2026-10-15. В контексте,
    #: потому что shutdown() останавливает её до закрытия соединения с HA.
    ac_protection: Any = None
    deployment: Any = None
    #: Наблюдение за локациями (спека 016): последние показания датчиков и
    #: снимки. Нужно интерфейсу, чтобы отдавать снимок и историю.
    location_state: Any = None
    #: Зеркало снимков в Home Assistant через MQTT (спека 016).
    location_mirror: Any = None

    async def shutdown(self) -> None:
        """Idempotent shutdown: watchdog, adapter, FSM engine, dispatcher cleanup loop.

        Порядок важен: сторож читает состояния движка, поэтому он останавливается
        первым, а движок — после него (FR-017).
        """
        # ВИДИМО: shutdown() — единственный вызывающий adapter.stop() в рантайме
        # (#70). Запись нужна, чтобы отличить остановку по внешнему сигналу от
        # остановки внутри процесса; на info она не видна.
        logger.warning("Container.shutdown() called")
        if self.watchdog is not None:
            await self.watchdog.stop()
        # Суточный цикл останавливается до адаптера: он шлёт команды в HA, и
        # остановка соединения раньше расписания означала бы неотправленные
        # события в журнале отказа при штатном выключении.
        if self.day_cycle is not None:
            await self.day_cycle.stop()
            self.day_cycle = None
        # Сверка вечернего света — такой же фоновой исполнитель, как суточный
        # цикл: она тоже шлёт команды в HA, поэтому останавливается до адаптера.
        if self.deco_watcher is not None:
            await self.deco_watcher.stop()
            self.deco_watcher = None
        # Защита кондиционера тоже шлёт команду (гасит недопустимое охлаждение),
        # поэтому останавливается до закрытия соединения.
        if self.ac_protection is not None:
            await self.ac_protection.stop()
            self.ac_protection = None
        await self.adapter.stop()
        await self.fsm.shutdown()
        await self.dispatcher.stop()


if TYPE_CHECKING:
    from core.services.day_cycle import DayCycleService
    from core.services.deco_light_watcher import DecorativeLightWatcher


class Container:
    """
    Lightweight Dependency Injection Container with lazy initialization.

    This container creates and manages platform components, ensuring
    proper dependency ordering and enabling easy mocking for tests.

    Example usage:
        ```python
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        context = container.build()

        # Or access components individually:
        engine = container.engine
        adapter = container.adapter
        ```
    """

    def __init__(
        self,
        manifest_path: str | None = None,
        manifest: Manifest | None = None,
        config_overrides: dict[str, Any] | None = None,
    ):
        """
        Initialize the DI container.

        Args:
            manifest_path: Path to the manifest YAML file.
            manifest: Pre-loaded manifest (alternative to manifest_path).
            config_overrides: Optional configuration overrides.
        """
        self._manifest_path = manifest_path
        self._manifest = manifest
        self._config_overrides = config_overrides or {}

        # Lazy-initialized components
        self._event_bus: EventBus | None = None
        self._metrics: Any | None = None
        self._metrics_reporter: Any | None = None
        self._watchdog: Any | None = None
        self._fsm_bridge: Any | None = None
        self._fsm: FSMEngine | None = None
        self._control_tracker: ControlTracker | None = None
        self._event_router: EventRouter | None = None
        self._adapter: HAAdapter | MockAdapter | None = None
        self._dispatcher: CommandDispatcher | None = None
        self._middleware: ManualLockoutMiddleware | None = None
        # Суточный цикл света создаётся при сборке по правилам манифеста.
        self._day_cycle: DayCycleService | None = None
        self._deco_watcher: DecorativeLightWatcher | None = None
        self._ventilation_watchdog: Any | None = None
        # Наблюдение за локациями (спека 016): снимки и история.
        self._location_state: Any | None = None
        #: Фоновая задача первичного чтения показаний локаций.
        self._location_prime_task: Any | None = None
        #: Зеркало снимков локаций в Home Assistant (спека 016).
        self._location_mirror: Any | None = None
        self._registry: Registry | None = None
        self._factory: FSMFactory | None = None
        self._deployment: DeploymentManager | None = None

    @property
    def manifest(self) -> Manifest:
        """Load and return the manifest (cached)."""
        if self._manifest is None:
            if self._manifest_path is None:
                msg = "Manifest path not provided"
                raise RuntimeError(msg)
            self._manifest = load_manifest(self._manifest_path)
        return self._manifest

    @property
    def event_bus(self) -> EventBus:
        """Get or create EventBus instance."""
        if self._event_bus is None:
            self._event_bus = EventBus()
        return self._event_bus

    @property
    def fsm(self) -> FSMEngine:
        """Get or create FSMEngine instance.

        Движок получает шину событий (публикует переходы) и хранилище состояний
        (FR-015). Диспетчер команд связывается отдельно в build(): он создаётся
        после движка, т.к. зависит от адаптера, а адаптер — от движка (R-01).
        """
        if self._fsm is None:
            self._fsm = FSMEngine(
                event_bus=self.event_bus,
                persistence=self._create_state_persistence(),
            )
        return self._fsm

    def _create_state_persistence(self) -> Any | None:
        """Создать хранилище состояний автоматов.

        Импорт выполняется внутри метода: пакет ``core.persistence`` тянет
        ``src.core.*``, что создаёт циклический импорт с контейнером.

        Returns:
            Экземпляр хранилища либо None, если хранилище создать не удалось.
        """
        try:
            from core.persistence.state_persistence import StatePersistence

            return StatePersistence()
        except (OSError, ImportError) as e:
            logger.warning(f"FSM state persistence unavailable: {e}")
            return None

    @property
    def control_tracker(self) -> ControlTracker:
        """Get or create ControlTracker instance.

        Трекер сохраняет последнее ручное действие на диск и восстанавливает его
        при старте. Без этого блокировка жила бы только в памяти процесса:
        перезапуск стирал бы её, и человек видел бы, что выключил свет, а через
        минуту свет включался снова — то есть ровно в тот момент, когда он и
        проверяет, работает ли платформа (спека 010, US1, R-03).
        """
        if self._control_tracker is None:
            self._control_tracker = ControlTracker(
                history_size=100,
                store=ManualControlStore(),
                restore=True,
            )
        return self._control_tracker

    @property
    def event_router(self) -> EventRouter:
        """Get or create EventRouter instance (depends on manifest and fsm)."""
        if self._event_router is None:
            self._event_router = EventRouter(manifest=self.manifest, engine=self.fsm)
        return self._event_router

    @property
    def deployment(self) -> DeploymentManager:
        """Менеджер развёртывания: режим тени и активного режима (#77).

        Создаётся один раз и передаётся адаптеру, потому что `SHADOW_MODE`
        действует именно на выход в Home Assistant. Раньше переменная доходила
        до контейнера и не читалась ни одной строкой кода.
        """
        if self._deployment is None:
            self._deployment = DeploymentManager.from_env()
        return self._deployment

    @property
    def adapter(self) -> HAAdapter | MockAdapter:
        """Get or create adapter instance (depends on fsm and event_router)."""
        if self._adapter is None:
            ws_url = os.environ.get("HA_WEBSOCKET_URL", "ws://localhost:8123/api/websocket")
            ha_token = os.environ.get("HA_TOKEN")

            if ha_token:
                self._adapter = HAAdapter(
                    mode="websocket",
                    engine=self.fsm,
                    event_router=self.event_router,
                    ws_url=ws_url,
                    token=ha_token,
                    deployment=self.deployment,
                    # Ручная блокировка обязана слышать живые события дома:
                    # адаптер вызывает record_manual_control при user_id в
                    # конверте события, и без этого параметра вызов молчит
                    # (в тестах #18 middleware инжектировали напрямую,
                    # контейнер — нет; дефект вскрыт живой проверкой
                    # 2026-10-08). Цикла нет: middleware зависит только от
                    # манифеста и трекера.
                    manual_lockout_middleware=self.middleware,
                )
                # Манифест отдаётся адаптеру для фильтра подписки: без него HA
                # присылает все сущности дома (в бою 1502 против 6 описанных),
                # и платформа отбивает каждое событие лишней сущности.
                self._adapter._manifest = self.manifest
                # Таймеры обогревателей нужны адаптеру, чтобы прочитать у них
                # единицу измерения (боевой дефект 2026-10-11: таймер измеряется
                # в секундах, а команда уходила минутами, и обогрев молчал сутки).
                heater_timers = self._heater_timer_entities()
                if heater_timers:
                    self._adapter.heater_timers = list(heater_timers)
                    self._adapter.heater_timer_of = self._heater_timer_pairs()
                # Модификатор «мы спим» — сущность Home Assistant, которой
                # владелец управляет сам (автоматизацией на своё расписание).
                # Платформа читает состояние и по нему решает, можно ли
                # включать яркий свет; без имени сущности условие его просто
                # не найдёт и решит по солнцу.
                sleep_modifier = self.manifest.automation_rules.lighting.sleep_modifier
                if sleep_modifier:
                    self._adapter.sleep_modifier_entity = sleep_modifier
                    # Включение модификатора гасит свет: клиент адаптера ловит
                    # переключение и зовёт этот колбэк («свет над столом
                    # выключается по модификатору», требование владельца
                    # 2026-10-09).
                    self._adapter.on_sleep_started = self._on_sleep_started
                    logger.info(
                        f"Модификатор «мы спим»: {sleep_modifier} — состояние "
                        "владелец задаёт сам, платформа только читает"
                    )
                # Закат и рассвет нужны декоративному свету независимо от
                # модификатора, поэтому подключаются всегда.
                self._adapter.on_sunset = self._on_sunset
                self._adapter.on_sunrise = self._on_sunrise

                # Уставка, сезон, потолок комфорта и выключалка вентиляции —
                # те же глобальные признаки, только климата и вентиляции.
                # Без них условия получают «данных нет»: до 2026-10-10 писателя
                # не существовало, и обогрев не включался ни в одной комнате.
                self._bind_global_entities()
            else:
                self._adapter = MockAdapter(engine=self.fsm)
                self._adapter.set_event_router(self.event_router)
        return self._adapter

    def _bind_global_entities(self) -> None:
        """Передать адаптеру имена глобальных сущностей климата и вентиляции.

        Имена берутся из правил дома, значения читает адаптер при подключении.
        Роль в правилах совпадает с ролью в таблице ``GLOBAL_ENTITY_FIELDS``,
        поэтому сопоставление не выдумывает имён: неизвестная роль молча
        останется без сущности, и условие получит «данных нет».

        Returns:
            Ничего.
        """
        rules = self.manifest.automation_rules
        adapter = self._adapter
        if adapter is None:
            return
        for field_name in (
            "setpoint_entity",
            # Термостат — источник истины для уставки и зеркало слайдера:
            # синхронизатору нужно знать имя сущности, но его цель живёт в
            # атрибуте, поэтому в контекст событий поле не попадает.
            "thermostat_entity",
            "comfort_max_entity",
            "season_entity",
            "feature_entity",
            "ac_gate_entity",
        ):
            role = field_name.removesuffix("_entity")
            entity = getattr(rules.climate, field_name, None)
            if entity:
                adapter.climate_entities[role] = entity

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

        logger.info(
            f"Глобальные сущности: климат {adapter.climate_entities}, "
            f"вентиляция {adapter.ventilation_entities}, шторы {adapter.cover_entities}"
        )

    @property
    def dispatcher(self) -> CommandDispatcher:
        """Get or create CommandDispatcher instance (depends on adapter)."""
        if self._dispatcher is None:
            # MockAdapter.call_service возвращает None, а HAAdapterProtocol объявляет bool;
            # dispatcher результат вызова игнорирует (dispatcher.py:192), поэтому
            # расхождение безвредно. cast() ничего не меняет во время выполнения.
            self._dispatcher = CommandDispatcher(
                ha_adapter=cast(HAAdapterProtocol, self.adapter), middlewares=[]
            )
            # Add middleware if available
            self._dispatcher.add_middleware(self.middleware)
        return self._dispatcher

    def _heater_timer_entities(self) -> list[str]:
        """Собрать таймеры обогревателей, объявленные в манифесте.

        Нужны адаптеру, чтобы прочитать у них единицу измерения до первого
        решения: команда в секундах вместо минут (или наоборот) выглядит
        снаружи как исправная работа — обогреватель включается и гаснет.

        Returns:
            Идентификаторы таймеров без повторов, в порядке манифеста.
        """
        timers: list[str] = []
        seen: set[str] = set()
        for room in self.manifest.rooms:
            for device in room.devices:
                for behavior in device.behaviors:
                    timer = (behavior.params or {}).get("heater_timer")
                    if isinstance(timer, str) and timer and timer not in seen:
                        seen.add(timer)
                        timers.append(timer)
        return timers

    def _heater_timer_pairs(self) -> dict[str, str]:
        """Соответствие «сущность события → таймер обогревателя».

        Ключ — и сам обогреватель, и **датчик температуры его комнаты**: решение
        обогрева принимается по событию датчика, поэтому единица измерения
        таймера нужна именно когда приходит ``temperature_changed``. Без ключа
        по датчику действие получало ``timer_unit = None``, угадывало минуты и
        отправляло 15 вместо 900 секунд (боевой дефект 2026-10-11).

        Returns:
            Словарь ``{entity_id: entity_id таймера}``.
        """
        pairs: dict[str, str] = {}
        for room in self.manifest.rooms:
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

    @property
    def middleware(self) -> ManualLockoutMiddleware:
        """Get or create ManualLockoutMiddleware instance."""
        if self._middleware is None:
            self._middleware = ManualLockoutMiddleware(
                automation_rules=self.manifest.automation_rules,
                control_tracker=self.control_tracker,
            )
        return self._middleware

    @property
    def registry(self) -> Registry:
        """Get or create Registry instance.

        Помимо действий регистрируются встроенные guard'ы. Раньше здесь
        регистрировались только действия, поэтому все guard'ы из шаблонов
        (`is_day_time`, `is_manual_override_enabled`, `humidity_above_60`,
        `humidity_below_60`) отсутствовали в реестре: движок отклонял каждый
        переход, а платформа выглядела исправной (Known Issue про «Guard not
        found»).

        Порядок важен: guard'ам нужен `ControlTracker`, который создаётся раньше
        реестра, а `registry` обращается к нему через ленивое свойство.
        """
        if self._registry is None:
            self._registry = Registry()
            register_all_actions(self._registry)
            register_all_guards(self._registry, self.control_tracker)
        return self._registry

    @property
    def factory(self) -> FSMFactory:
        """Get or create FSMFactory instance (depends on fsm, registry, event_bus)."""
        if self._factory is None:
            self._factory = FSMFactory(
                engine=self.fsm, registry=self.registry, event_bus=self.event_bus
            )
        return self._factory

    @property
    def metrics(self) -> Any:
        """Get or create MetricsCollector instance.

        Инициализируется первым шагом ``build()``: сборщик нужен всем, кто уже
        пишет в показатели — сервису устройств, адаптеру и подписчику
        состояний, — и поздняя инициализация потеряла бы первые события (R-01).
        """
        if self._metrics is None:
            from core.metrics import get_metrics_collector

            self._metrics = get_metrics_collector()
            self._metrics.initialize()
        return self._metrics

    @property
    def metrics_reporter(self) -> Any:
        """Get or create MetricsReporter instance (depends on event_bus).

        Учёт переходов, отказов и восстановлений идёт подпиской на шину, а не
        правкой движка: ядро не должно зависеть от наличия коллектора
        (конституция I, R-03).
        """
        if self._metrics_reporter is None:
            from services.metrics_reporter import MetricsReporter

            self._metrics_reporter = MetricsReporter(self.event_bus, self.metrics)
        return self._metrics_reporter

    @property
    def watchdog(self) -> Any:
        """Get or create WatchdogService instance.

        Сторож — часть жизненного цикла платформы: создаётся в ``build()`` и
        останавливается в ``PlatformContext.shutdown()``. Отдельный путь
        остановки в ``main.py`` создал бы вторую точку, которую легко забыть
        (R-11, FR-017).
        """
        if self._watchdog is None:
            from services.watchdog import WatchdogService, watchdog_settings

            settings = watchdog_settings()
            if not settings.enabled:
                logger.info("Watchdog disabled (set WATCHDOG_ENABLED=0 to disable)")
            # В автономном режиме адаптера-заглушки нет смысла считать
            # источником внешней системы: её отсутствие не проблема (FR-014).
            self._watchdog = WatchdogService(
                fsm_engine=self.fsm,
                metrics=self.metrics,
                adapter=self._external_adapter(),
                settings=settings,
                event_bus=self.event_bus,
                # Расхождение из-за действующего оверрайда — уступка человеку,
                # а не отказ прибора: сторож спрашивает правило блокировки у
                # посредника, а не повторяет его у себя (концепция §7, п. 2).
                manual_override_supplier=self._manual_override_active,
            )
        return self._watchdog

    def _external_adapter(self) -> Any:
        """Адаптер внешней системы, если он есть.

        Returns:
            Адаптер либо ``None`` в автономном режиме.
        """
        from adapters.ha_adapter import HomeAssistantAdapter

        adapter = self.adapter
        return adapter if isinstance(adapter, HomeAssistantAdapter) else None

    def _manual_override_active(self, device_id: str) -> bool:
        """Действует ли для прибора ручная блокировка (концепция §7, п. 2).

        Args:
            device_id: Сущность прибора.

        Returns:
            True, если человек вмешался и срок оверрайда ещё не истёк.
        """
        middleware = self._middleware
        if middleware is None:
            return False
        try:
            return bool(middleware.is_lockout_active(device_id))
        except Exception as exc:  # noqa: BLE001 — наблюдатель не должен падать
            logger.warning(f"Проверка ручной блокировки для {device_id} не удалась: {exc}")
            return False

    def _ventilation_context(self, entity_id: str) -> dict[str, Any]:
        """Общие признаки дома для подтверждения решения вентиляции (B63).

        Собираются из тех же источников, что у маршрутизатора: глобальные
        значения адаптера (уличная температура, сезон, флаги) и показания
        комнаты с признаком обогрева из `EventRouter.settings_context`. Один
        источник контекста на оба пути — иначе подтверждение шло с пустыми
        признаками, и условие «приток по погоде» отказывало `guard_data_missing`.

        Args:
            entity_id: Автомат вентиляции.

        Returns:
            Словарь признаков; пустой, если источники недоступны.
        """
        context: dict[str, Any] = {}
        builder = getattr(self._adapter, "event_context", None)
        if callable(builder):
            with contextlib.suppress(Exception):
                context.update(builder(entity_id))
        with contextlib.suppress(Exception):
            context.update(self.event_router.settings_context(entity_id))
        return context

    @property
    def fsm_bridge(self) -> Any:
        """Get or create FSMStateBridge (depends on event_bus, dispatcher).

        Мост доставляет каждый переход автомата потребителям состояния: журналу
        переходов, зеркалу Home Assistant и живым обновлениям (FR-015, FR-024).
        """
        if self._fsm_bridge is None:
            from services.fsm_state_bridge import FSMStateBridge

            self._fsm_bridge = FSMStateBridge(
                event_bus=self.event_bus,
                dispatcher=self.dispatcher,
                event_store=self._create_event_store(),
            )
        return self._fsm_bridge

    def _create_event_store(self) -> Any:
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

    async def announce_started(self) -> None:
        """Оповестить подписчиков о завершении инициализации платформы.

        Событие ``platform.started`` ожидают подписчики восстановления состояний
        и менеджер контекста; раньше оно не публиковалось никогда, поэтому эти
        подписчики были мертвы (FR-007).

        Returns:
            Ничего не возвращает; результат доставки логируется шиной.
        """
        await self.event_bus.publish(
            EVENT_PLATFORM_STARTED,
            {"manifest": str(self._manifest_path) if self._manifest_path else ""},
        )

    def build(self) -> PlatformContext:
        """
        Build and return the complete platform context.

        This triggers lazy initialization of all components in the correct order.

        Returns:
            PlatformContext with all initialized components.
        """
        # Access properties in dependency order to ensure proper initialization
        _ = self.event_bus  # No dependencies
        # Метрики и подписчик — до всего остального: сборщик нужен адаптеру и
        # сервису устройств, поэтому первые же события не должны потеряться
        # (R-01).
        _ = self.metrics  # No dependencies
        _ = self.metrics_reporter  # Depends on event_bus, metrics
        _ = self.fsm  # No dependencies
        _ = self.control_tracker  # No dependencies
        _ = self.factory  # Depends on fsm, registry, event_bus

        # Create and register FSMs from manifest BEFORE EventRouter:
        # EventRouter builds its sensor->FSM mapping once in __init__
        # from engine.get_entities_by_device(), so FSMs must already exist.
        self.factory.create_and_register(self.manifest)
        self._publish_fsm_inventory()

        _ = self.event_router  # Depends on manifest, fsm (mapping built here)
        _ = self.adapter  # Depends on fsm, event_router
        _ = self.dispatcher  # Depends on adapter, middleware

        # Link dispatcher to FSM engine: the engine exists before the dispatcher
        # (dispatcher depends on adapter, adapter depends on engine), so the
        # cyclic dependency is broken here. Without this, CommandIntents from FSM
        # actions are dropped and automation never reaches devices (R-01, FR-016).
        self.fsm.set_command_dispatcher(self.dispatcher)

        # Start TTL cleanup loop when a running event loop exists
        # (sync build() in tests runs without a loop — start is skipped)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self.dispatcher.start()

        # Link adapter to FSM engine
        self.adapter.set_fsm_engine(self.fsm)

        # Мост состояний: подписывается на переходы и обслуживает журнал,
        # зеркало Home Assistant и живые обновления (FR-015).
        _ = self.fsm_bridge

        # Сторож: цикл проверок запускается, только если работает цикл событий
        # и сторож не выключен настройкой (FR-017, FR-019).
        self._start_watchdog()
        self._start_day_cycle()
        self._start_deco_watcher()
        self._start_ventilation_watchdog()
        self._start_ac_protection()
        self._start_sensor_health()
        self._start_location_state()

        return PlatformContext(
            day_cycle=self._day_cycle,
            deco_watcher=self._deco_watcher,
            ac_protection=self._ac_protection,
            manifest=self.manifest,
            event_bus=self.event_bus,
            fsm=self.fsm,
            control_tracker=self.control_tracker,
            adapter=self.adapter,
            dispatcher=self.dispatcher,
            event_router=self.event_router,
            fsm_bridge=self.fsm_bridge,
            # Сторож обязан попасть в контекст: shutdown() останавливает его
            # первым, и без ссылки здесь проверка `if self.watchdog is not None`
            # была ложной, то есть мёртвой веткой. Сторож читает состояния
            # движка, поэтому порядок в shutdown() важен (FR-017).
            watchdog=self._watchdog,
            # Наблюдение за локациями (спека 016): снимок, история и зеркало.
            location_state=self._location_state,
            location_mirror=self._location_mirror,
            # Менеджер развёртывания обязан быть в контексте: режим должен быть
            # виден снаружи (`/health`), иначе оператор снова не может отличить
            # режим тени от активного — ровно тот случай, что породил #77.
            deployment=self.deployment,
        )

    def _start_watchdog(self) -> None:
        """Запустить цикл проверок сторожа, если это возможно.

        В синхронной сборке (тесты, ``Container.build()`` без цикла событий)
        запуск пропускается: фоновая задача без работающего цикла завершилась
        бы сразу, и вместо тихой пустоты мы получили бы висящее задание.
        """
        watchdog = self.watchdog
        if not watchdog.settings.enabled:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Watchdog not started: no running event loop")
            return
        watchdog.start()

    def _start_day_cycle(self) -> None:
        """Запустить суточный цикл: гасить свет по часам, поднимать дом утром.

        Расписание берётся из правил освещения манифеста (`night_off_at`,
        `morning_at`) и живёт в часах дома: контейнер работает в UTC, и «23:00»
        здесь — это 23:00 дома, иначе свет гаснет в час ночи по-контейнерски.

        Как и сторож, не запускается без работающего цикла событий: фоновая
        задача без него завершилась бы сразу и оставила бы висящее задание.
        """
        from core.scheduling.daily import DailyClock
        from core.services.day_cycle import DayCycleService

        rules = self.manifest.automation_rules.lighting
        events: dict[Any, str] = {}
        for value, name in (
            (getattr(rules, "night_off_at", None), "quiet_hours_started"),
            (getattr(rules, "morning_at", None), "day_started"),
        ):
            if not value:
                continue
            try:
                hour, minute = (int(part) for part in str(value).split(":", 1))
            except ValueError:
                logger.warning(f"Расписание света «{value}» не разобрано: событие пропущено")
                continue
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                logger.warning(f"Расписание света «{value}» вне диапазона: событие пропущено")
                continue
            events[dt_time(hour, minute)] = name

        if not events:
            logger.info("Суточный цикл не задан: выключение по часам не работает")
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Суточный цикл не запущен: нет работающего цикла событий")
            return

        clock = DailyClock(events, timezone=self.house_timezone())
        self._day_cycle = DayCycleService(clock=clock, engine=self.fsm)
        self._day_cycle.start()
        logger.info(f"Суточный цикл света: {self._day_cycle.describe()}")

    async def _on_sleep_started(self) -> None:
        """Свет погасить, когда модификатор «мы спим» включился.

        Колбэк адаптера: клиент ловит переключение сущности в Home Assistant
        и зовёт этот метод. Доставка та же, что у событий суточного цикла, —
        событие уходит только автоматам, у которых на него есть переход, а
        не веером всем: остальные отвергли бы его как несвойственное.

        Почему выключение, а не просто «не включать»: требование владельца —
        «свет над столом выключается по модификатору мы спим». Если свет горит,
        когда владелец ложится спать, гаснуть он должен именно в этот момент,
        а не ждать движения или утреннего расписания.

        Returns:
            Ничего. Отказ одного автомата не мешает доставке остальным.
        """
        from core.services.day_cycle import deliver_to_automata

        recipients = self.fsm.entities_with_trigger("sleep_started")
        logger.info(
            "Модификатор «мы спим» включён: sleep_started "
            f"→ {len(recipients)} автоматов ({', '.join(recipients)})"
        )
        await deliver_to_automata(self.fsm, "sleep_started", "Модификатор «мы спим»")

    async def _on_sunset(self) -> None:
        """Солнце зашло: вечернему освещению пора включиться.

        Колбэк адаптера. Гирлянда на террасе и ночное освещение — не свет от
        движения, а вечерний свет: они включаются по закату, а не когда мимо
        кто-то прошёл (требование владельца 2026-10-09).

        Returns:
            Ничего.
        """
        from core.services.day_cycle import deliver_to_automata

        await deliver_to_automata(self.fsm, "sunset_started", "Закат")

    async def _on_sunrise(self) -> None:
        """Солнце взошло: ночному освещению пора погаснуть.

        Колбэк адаптера. Ночное освещение горит до рассвета — в отличие от
        гирлянды, которая гаснет по модификатору «мы спим».

        Returns:
            Ничего.
        """
        from core.services.day_cycle import deliver_to_automata

        await deliver_to_automata(self.fsm, "sunrise_started", "Рассвет")

    def _start_deco_watcher(self) -> None:
        """Запустить сверку вечернего света, если это возможно.

        Закат бывает один раз в сутки, и событие легко теряется: рестарт
        платформы вечером, обрыв связи в момент перехода через горизонт,
        поведение добавлено в манифест после заката. Всё это случилось в доме
        за один вечер, и ночное освещение не загорелось.

        Returns:
            Ничего.
        """
        adapter = self._adapter
        if adapter is None:
            return

        def _daylight() -> Any:
            return getattr(getattr(adapter, "_ws_client", None), "daylight", None)

        def _sleeping() -> Any:
            # Модификатор «мы спим»: по нему свет с `off_by: sleep` должен быть
            # выключен, и сверка не имеет права включать его обратно (боевой
            # дефект 2026-10-13: гирлянда вернулась через минуту после отбоя).
            return getattr(getattr(adapter, "_ws_client", None), "asleep", None)

        from core.services.deco_light_watcher import DecorativeLightWatcher

        self._deco_watcher = DecorativeLightWatcher(
            engine=self.fsm, daylight_supplier=_daylight, sleeping_supplier=_sleeping
        )
        # Как сторож и суточный цикл: в синхронной сборке (тесты, Container.build()
        # без цикла событий) запуск пропускается — фоновая задача без работающего
        # цикла завершилась бы сразу, и вместо тихой пустоты осталось бы висящее
        # задание.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Сверка вечернего света не запущена: нет работающего цикла событий")
            self._deco_watcher = None
            return
        self._deco_watcher.start()
        logger.info(f"Сверка вечернего света: {self._deco_watcher.describe()}")

    def _start_ac_protection(self) -> None:
        """Запустить защиту кондиционера.

        Зимнее охлаждение портит технику, и правило не зависит от автоматики:
        кондиционер может работать без участия платформы (включён владельцем или
        автоматизацией Home Assistant). Служба смотрит фактический режим прибора
        и правила дома — те же, что у автоматов.

        Returns:
            Ничего.
        """
        from core.services.ac_protection import AirConditionerProtection

        climate = getattr(self.manifest.automation_rules, "climate", None)
        entities = list(getattr(climate, "ac_entities", []) or [])
        min_temp = float(getattr(climate, "ac_min_outside_temp", 5.0) or 5.0)
        self._ac_protection = AirConditionerProtection(
            # Именно свойство `adapter`: адаптер создаётся лениво, и приватное
            # поле на момент сборки ещё пусто — защита молчала бы всегда.
            adapter=self.adapter,
            dispatcher=self.dispatcher,
            entities=entities,
            min_outside_temp=min_temp,
        )
        self._ac_protection.subscribe(self.event_bus)
        if self._ac_protection.start():
            logger.info(f"Защита кондиционера: под наблюдением {len(entities)} прибор(ов)")

    def _start_ventilation_watchdog(self) -> None:
        """Запустить сторожа вентиляции (защита от дрейфа прибора).

        Рекуператор может «соскочить» с заданного режима сам, между событиями
        датчика: в бою 2026-10-13 платформа отправляла «Приток MAX», а через
        2–5 минут прибор снова стоял на «Рекуперации (зиме)», и вернуть его было
        нечем. Второе наблюдение того же дня (B54): прибор может быть
        **остановлен**, хотя автомат считает себя в работе — команда принята
        Home Assistant, но не применена прибором. Сторож раз в интервал
        подтверждает решение автоматов вентиляции и читает настоящее состояние
        прибора: остановленному сообщается одноразовый факт `_device_is_off`, и
        шаблон подтверждает решение включением.

        Returns:
            Ничего.
        """
        from core.services.ventilation_watchdog import VentilationWatchdog

        self._ventilation_watchdog = VentilationWatchdog(
            engine=self.fsm,
            adapter=self._adapter,
            context_supplier=self._ventilation_context,
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Сторож вентиляции не запущен: нет работающего цикла событий")
            self._ventilation_watchdog = None
            return
        self._ventilation_watchdog.start()
        logger.info(f"Сторож вентиляции: {self._ventilation_watchdog.describe()}")

    def _start_location_state(self) -> None:
        """Подписать наблюдение за локациями на изменения состояний (спека 016).

        Снимок собирается из событий шины ``state_change``, которые публикует
        адаптер после фильтра подписки. Единицы измерения берутся у адаптера:
        они читаются из Home Assistant, а не дублируются в манифесте — второе
        место правды разошлось бы с домом.

        Returns:
            Ничего.
        """
        if self._location_state is not None:
            return
        from core.services.location_state import LocationStateService

        adapter = self._adapter
        unit_provider = getattr(adapter, "get_entity_unit", None)
        state_reader = getattr(adapter, "get_entity_state", None)
        self._location_state = LocationStateService(
            self.manifest, unit_provider=unit_provider, state_reader=state_reader
        )
        self._location_state.subscribe(self.event_bus)
        self._location_mirror = self._build_location_mirror(adapter)
        self._location_mirror.bind(self.event_bus)
        self._schedule_location_prime()

    def _build_location_mirror(self, adapter: Any) -> Any:
        """Собрать зеркало локаций в Home Assistant (спека 016, FR-008).

        Публикация идёт через адаптер (``mqtt.publish``): ``core`` не импортирует
        ``adapters``. Без адаптера зеркало собирается выключенным — снимок и
        журнал от этого не страдают (FR-009).

        Args:
            adapter: Адаптер Home Assistant либо ``None``.

        Returns:
            Зеркало локаций.
        """
        from core.services.location_mirror import LocationMirror

        rules = self.manifest.automation_rules.locations
        publisher = None
        if adapter is not None:

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

            publisher = _publish

        return LocationMirror(
            state=self._location_state,
            publish=publisher,
            prefix=rules.mqtt_prefix,
            enabled=rules.mirror_enabled,
        )

    def _schedule_location_prime(self) -> None:
        """Прочитать текущие показания датчиков, когда появится связь с домом.

        Снимок собирается из событий, а событий на старте нет: читаем значения
        сами — иначе «что сейчас в комнате» неизвестно до первого изменения
        (FR-001). Чтение идёт в фоне и не мешает сборке платформы; без рабочего
        цикла событий задача не создаётся.

        Returns:
            Ничего.
        """
        service = self._location_state
        adapter = self._adapter
        if service is None or adapter is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Первичное чтение локаций не запущено: нет работающего цикла")
            return

        async def _prime() -> None:
            """Дождаться связи с домом, узнать единицы и прочитать показания."""
            for _ in range(60):
                if getattr(adapter, "is_connected", False):
                    break
                await asyncio.sleep(1.0)
            # Единицы — до показаний: снимок без единицы нельзя ни сравнить, ни
            # нарисовать, а кэш единиц заполняется только таймерами обогрева.
            refresh = getattr(adapter, "refresh_units", None)
            if refresh is not None:
                with contextlib.suppress(Exception):
                    await refresh(service.bound_entities())
            try:
                await service.prime()
            except Exception as exc:  # noqa: BLE001 — чтение не должно ронять платформу
                logger.warning(f"Первичное чтение локаций не удалось: {exc}")
            mirror = self._location_mirror
            if mirror is not None:
                try:
                    await mirror.publish_all()
                except Exception as exc:  # noqa: BLE001 — зеркало не важнее снимка
                    logger.warning(f"Зеркало локаций не опубликовано: {exc}")

        self._location_prime_task = asyncio.create_task(_prime())

    @property
    def location_state(self) -> Any:
        """Наблюдение за локациями (спека 016).

        Сервис создаётся по требованию: интерфейсу он нужен и тогда, когда
        ``build()`` ещё не вызывался.

        Returns:
            Сервис наблюдения: снимки локаций и их история.
        """
        self._start_location_state()
        return self._location_state

    def _start_sensor_health(self) -> None:
        """Запустить наблюдение за батарейками датчиков, если это возможно.

        Датчик на севшей батарейке замолкает, и о проблеме узнают по молчанию —
        то есть потеряв датчик. Наблюдение читает заряд заранее и предупреждает,
        пока датчик ещё жив.

        Returns:
            Ничего.
        """
        adapter = self._adapter
        if adapter is None:
            return

        # Батарейка названа по датчику: ESPHome публикует заряд отдельной
        # сущностью с тем же префиксом. Список берётся из манифеста, а не
        # сканируется по дому: подписка на всё — Known Issue #82.
        batteries: list[str] = []
        for room in self.manifest.rooms:
            for sensor_id in all_sensor_entities(room.sensors):
                if "_battery" not in sensor_id:
                    batteries.append(f"{sensor_id.rsplit('_', 1)[0]}_battery")

        # Датчики вне манифеста (уличные, терраса) в список не попадают, хотя
        # их батарейки тоже садятся: добавляются явно в правилах дома.
        rules = self.manifest.automation_rules
        for domain in (rules.lighting, rules.climate, rules.ventilation):
            for entity in getattr(domain, "battery_watch_entities", None) or ():
                if entity not in batteries:
                    batteries.append(entity)

        if not batteries:
            return

        from core.services.sensor_health import SensorHealthService

        self._sensor_health: Any = SensorHealthService(adapter=adapter, battery_entities=batteries)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Наблюдение за батарейками не запущено: нет работающего цикла событий")
            self._sensor_health = None
            return
        self._sensor_health.start()
        logger.info(f"Наблюдение за батарейками: {batteries}")

    def house_timezone(self) -> Any:
        """Часовой пояс дома из правил автоматизации.

        Returns:
            ``ZoneInfo`` дома либо пояс процесса, если не задан.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        name = getattr(self.manifest.automation_rules, "time_zone", None)
        if name:
            try:
                return ZoneInfo(name)
            except ZoneInfoNotFoundError:
                logger.warning(f"time_zone={name!r} неизвестен: беру часовой пояс процесса")
        return ZoneInfo("UTC")

    def _publish_fsm_inventory(self) -> None:
        """Опубликовать число зарегистрированных автоматов в показателях.

        Число берётся из публичного состояния движка, поэтому ради одного
        счётчика не приходится менять сам движок (R-05).
        """
        try:
            self.metrics.set_active_fsm_count(self._manifest_name(), len(self.fsm.get_all_states()))
        except Exception as exc:  # noqa: BLE001 - показатели не влияют на запуск
            logger.warning(f"Failed to publish FSM inventory metric: {exc}")

    def _manifest_name(self) -> str:
        """Имя объекта для метки показателя активных автоматов.

        Returns:
            Имя инстанса из манифеста либо пустая строка, если манифест не задан.
        """
        manifest = self.manifest
        if manifest is None:
            return ""
        return manifest.instance.name or manifest.instance.id

    def reset(self) -> None:
        """Reset all cached instances for testing purposes."""
        self._event_bus = None
        # Сборщик показателей — глобальный синглтон: сбрасывать ссылку можно,
        # сам синглтон переиспользуется следующим контейнером в том же процессе.
        self._metrics_reporter = None
        self._fsm_bridge = None
        self._fsm = None
        self._control_tracker = None
        self._event_router = None
        self._adapter = None
        self._dispatcher = None
        self._middleware = None
        self._registry = None
        self._factory = None
        # Don't reset manifest as it's expensive to reload
