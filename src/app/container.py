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
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from adapters.ha_adapter import HAAdapter
from adapters.mock_adapter import MockAdapter
from app.context import PlatformContext as PlatformContext
from app.factories import (
    bind_global_entities,
    create_adapter,
    create_event_store,
    create_external_adapter,
    create_state_persistence,
    heater_timer_entities,
    heater_timer_pairs,
)
from app.house_services import ContainerHouseMixin
from app.lifecycle import ContainerLifecycleMixin
from core.action_handlers import register_all_actions
from core.commands.dispatcher import CommandDispatcher, CommandIntent, HAAdapterProtocol
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.deployment_manager import DeploymentManager
from core.events.event_bus import EventBus
from core.events.event_router import EventRouter
from core.events.fsm_events import EVENT_HA_CONNECTED, EVENT_PLATFORM_STARTED
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import register_all_guards
from core.models.manifest import (
    Manifest,
    load_manifest,
)
from core.persistence.manual_control_store import ManualControlStore
from core.registry import Registry


if TYPE_CHECKING:
    from core.services.day_cycle import DayCycleService
    from core.services.deco_light_watcher import DecorativeLightWatcher


class Container(ContainerLifecycleMixin, ContainerHouseMixin):
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
        #: Служба глобальной цветовой температуры света (день → вечер → ночь).
        self._light_color_temperature: Any | None = None
        #: Обход дома (BACKLOG F6): проблемы и реестр показаний.
        self._house_health: Any | None = None
        #: Чистка мусора во вспомогательных элементах (BACKLOG B77).
        self._helper_cleanup: Any | None = None
        # Наблюдение за локациями (спека 016): снимки и история.
        self._location_state: Any | None = None
        #: Фоновая задача первичного чтения показаний локаций.
        self._location_prime_task: Any | None = None
        #: Зеркало снимков локаций в Home Assistant (спека 016).
        self._location_mirror: Any | None = None
        #: Зеркало проблем дома (карточка тревог на дашборде, B79).
        self._platform_mirror: Any | None = None
        #: Подпись последней опубликованной сводки проблем (повтор не шлём).
        self._problems_signature: Any | None = None
        #: Фоновая задача слежения за проблемами автоматов.
        self._problems_task: Any | None = None
        #: Зеркало состояний автоматов в помощники Home Assistant (B79).
        self._fsm_helper_mirror: Any | None = None
        #: Фоновая задача создания помощников и первой записи состояний.
        self._fsm_helper_task: Any | None = None
        self._registry: Registry | None = None
        self._factory: FSMFactory | None = None
        self._deployment: DeploymentManager | None = None
        #: Стартовая сверка света выполняется один раз — после первого
        #: подключения к Home Assistant.
        self._startup_light_cleanup_done = False

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
                persistence=create_state_persistence(),
            )
        return self._fsm

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
            self._adapter = create_adapter(
                engine=self.fsm,
                event_router=self.event_router,
                deployment=self.deployment,
                middleware=self.middleware,
                manifest=self.manifest,
                heater_timers=heater_timer_entities(self.manifest),
                heater_timer_pairs=heater_timer_pairs(self.manifest),
                on_sleep_started=self._on_sleep_started,
                on_sunset=self._on_sunset,
                on_sunrise=self._on_sunrise,
            )
        return self._adapter

    def _bind_global_entities(self) -> None:
        """???????? ???????? ????? ?????????? ????????? ??????? ? ??????????."""
        if self._adapter is None:
            return
        bind_global_entities(self._adapter, self.manifest)

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
            register_all_guards(
                self._registry,
                self.control_tracker,
                automation_rules=self._manifest_rules(),
            )
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
                adapter=create_external_adapter(self.adapter),
                settings=settings,
                event_bus=self.event_bus,
                # Расхождение из-за действующего оверрайда — уступка человеку,
                # а не отказ прибора: сторож спрашивает правило блокировки у
                # посредника, а не повторяет его у себя (концепция §7, п. 2).
                manual_override_supplier=self._manual_override_active,
                # Повтор решения — только за свой приказ (BACKLOG B86): расхождение
                # без нашего приказа значит чьё-то действие, и повторять своё
                # решение было бы спором с человеком.
                command_recency_supplier=getattr(self.adapter, "was_commanded_recently", None),
                # Стартовая сверка гасит лампу, включившуюся от появления
                # питания: это не действие человека.
                startup_light_off=self._turn_off_startup_light,
            )
        return self._watchdog

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
                event_store=create_event_store(),
            )
        return self._fsm_bridge

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
        await self._reconcile_startup_lights()

    async def _on_ha_connected(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Выполнить стартовую сверку света после подключения к HA.

        Args:
            event_type: Имя события.
            payload: Полезная нагрузка.
            trace_id: Идентификатор трассы.
        """
        del event_type, payload, trace_id
        await self._reconcile_startup_lights()

    async def _reconcile_startup_lights(self) -> None:
        """Погасить лампы, включившиеся от появления питания.

        После перезапуска Home Assistant может прислать «лампа горит» без
        действия человека — прибор включился сам при возврате питания. Сторож
        видит расхождение с решением автомата, но обычная проверка уступает
        ручной блокировке. Здесь выполняется одна стартовая проверка: для лампы
        с решением «выключено» блокировка снимается, и команда выключения идёт
        обычным путём через автомат.

        Returns:
            Ничего. Неудача сверки не мешает платформе работать.
        """
        if self._startup_light_cleanup_done:
            return
        adapter = self._adapter
        if adapter is None or not getattr(adapter, "is_connected", False):
            return
        self._startup_light_cleanup_done = True
        try:
            await self.watchdog.check_once(startup=True)
        except Exception as exc:  # noqa: BLE001 — стартовая сверка не должна ронять запуск
            logger.warning(f"Стартовая сверка света не удалась: {exc}")

    async def _turn_off_startup_light(self, device_id: str) -> None:
        """Погасить лампу, включившуюся от появления питания.

        Команда идёт через диспетчер, но с `bypass_lockout`: ручная блокировка,
        сохранившаяся до перезапуска, не должна оставлять свет горящим.
        Состояние автомата уже «выключено», поэтому переход не нужен — команда
        приводит прибор к принятому решению.

        Args:
            device_id: Сущность лампы.

        Returns:
            Ничего.
        """
        intent = CommandIntent(
            device_id=device_id,
            domain=device_id.split(".", 1)[0],
            service="turn_off",
            data={},
            priority=50,
            source="startup_cleanup",
            bypass_lockout=True,
        )
        await self.dispatcher.submit(intent)

    def build(self) -> PlatformContext:
        """
        Build and return the complete platform context.

        This triggers lazy initialization of all components in the correct order.

        Returns:
            PlatformContext with all initialized components.
        """
        # Access properties in dependency order to ensure proper initialization
        _ = self.event_bus  # No dependencies
        # Стартовая сверка света ждёт первого подключения к Home Assistant:
        # adapter.start() не блокирует, и сразу после запуска связи ещё нет.
        self.event_bus.subscribe(EVENT_HA_CONNECTED, self._on_ha_connected)
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
        self._start_light_color_temperature()
        self._start_ac_protection()
        _ = self.house_health  # обход дома: собрать и запустить (BACKLOG F6)
        self._start_sensor_health()
        self._start_location_state()
        self._start_fsm_helpers()
        self._start_problems_watch()

        return PlatformContext(
            day_cycle=self._day_cycle,
            deco_watcher=self._deco_watcher,
            ac_protection=self._ac_protection,
            house_health=self._house_health,
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
        self._startup_light_cleanup_done = False
        # Don't reset manifest as it's expensive to reload
