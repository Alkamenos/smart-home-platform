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
from datetime import datetime as dt_datetime, time as dt_time
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
    create_location_mirror,
    create_platform_mirror,
    create_state_persistence,
    heater_timer_entities,
    heater_timer_pairs,
)
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
    load_manifest,
    role_entities,
)
from core.persistence.manual_control_store import ManualControlStore
from core.registry import Registry


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

        Расписание берётся из раздела дома ``automation_rules.schedule``
        (`night_off_at`, `morning_at`) и живёт в часах дома: контейнер работает в
        UTC, и «23:00» здесь — это 23:00 дома, иначе свет гаснет в час ночи
        по-контейнерски.

        Как и сторож, не запускается без работающего цикла событий: фоновая
        задача без него завершилась бы сразу и оставила бы висящее задание.
        """
        from core.scheduling.daily import DailyClock
        from core.services.day_cycle import DayCycleService

        schedule = self.manifest.automation_rules.schedule
        events: dict[Any, str] = {}
        for value, name in (
            (getattr(schedule, "night_off_at", None), "quiet_hours_started"),
            (getattr(schedule, "morning_at", None), "day_started"),
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

        def _scheduled_light_feature() -> Any:
            # Разрешение владельца на автоматическое включение планового света.
            return getattr(
                getattr(adapter, "_ws_client", None),
                "scheduled_light_enabled",
                None,
            )

        from core.guards.context import HOUSE_TZ
        from core.services.deco_light_watcher import DecorativeLightWatcher

        def _now() -> dt_datetime:
            # Часы дома, а не контейнера: контейнер живёт в UTC, и «до полудня»
            # по UTC сдвинуло бы границу утра на пять часов.
            return dt_datetime.now(HOUSE_TZ)

        self._deco_watcher = DecorativeLightWatcher(
            engine=self.fsm,
            daylight_supplier=_daylight,
            sleeping_supplier=_sleeping,
            now_supplier=_now,
            scheduled_light_feature_supplier=_scheduled_light_feature,
            scheduled_light_entities=self._scheduled_light_entities(),
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

    def _scheduled_light_entities(self) -> set[str]:
        """Имена автоматов, включающихся по закату только с разрешения флага.

        Сверка вечернего света перебирает все автоматы с триггером
        ``sunset_started``. Плановому свету она не должна повторять закат при
        выключенном флаге: это штатное решение, а не расхождение. Список
        собирается по манифесту тем же правилом имён, что и фабрика автоматов.

        Returns:
            Множество идентификаторов автоматов ``scheduled_light``.
        """
        from core.fsm.naming import fsm_entity_id

        entities: set[str] = set()
        for place in self.manifest.all_places:
            for device in getattr(place, "devices", []) or []:
                for behavior in device.behaviors:
                    if behavior.template != "scheduled_light":
                        continue
                    entities.add(fsm_entity_id(device.id, behavior.template, behavior.priority))
        return entities

    def _manifest_rules(self) -> Any:
        """Правила дома для встроенных условий.

        Реестр условий собирается и без манифеста — в тестах и при экспорте FSM.
        Требовать манифест здесь нельзя: прежде сборка реестра его не касалась, и
        обращение к нему сломало бы эти пути (найдено на прогоне). Без правил
        действуют запасные значения, и об этом пишется предупреждение.

        Returns:
            Правила дома либо ``None``.
        """
        if self._manifest is None and self._manifest_path is None:
            return None
        try:
            return self.manifest.automation_rules
        except Exception as exc:  # noqa: BLE001 — реестр важнее настроек
            logger.warning(f"Настройки дома для условий не прочитаны: {exc}")
            return None

    @property
    def house_health(self) -> Any:
        """Обход дома: проблемы и реестр показаний (BACKLOG F6).

        Создаётся при сборке и читается веб-слоем: интерфейсу нужен последний
        снимок — проблемы всех датчиков дома, а не только приборов манифеста.

        Returns:
            Служба обхода.
        """
        if self._house_health is None:
            from core.services.house_health import HouseHealthService

            self._house_health = HouseHealthService(
                adapter=self.adapter,
                areas=self._health_areas(),
                battery_types=dict(getattr(self.manifest, "battery_types", {}) or {}),
                on_report=self._platform_problems_publisher(),
            )
            if self._house_health.start():
                logger.info(
                    f"Обход дома: мест в реестре {len(self._house_health.areas)}, "
                    f"каждые {self._house_health.interval_minutes:g} мин"
                )
        return self._house_health

    @property
    def helper_cleanup(self) -> Any:
        """Чистка мусора во вспомогательных элементах (BACKLOG B77).

        Служба считает признак использования по фактам: манифест, правила
        автоматизаций Home Assistant, журнал платформы. Она **ничего не удаляет** —
        удаление вспомогательного элемента необратимо, а цена ошибки («сломалось
        тихо, заметили вечером») выше выгоды от автоматики.

        Returns:
            Служба чистки.
        """
        if self._helper_cleanup is None:
            from core.services.helper_cleanup import HelperCleanupService

            self._helper_cleanup = HelperCleanupService(
                adapter=self.adapter,
                manifest=self.manifest,
                event_store=create_event_store(),
            )
        return self._helper_cleanup

    def _health_areas(self) -> dict[str, tuple[str, str]]:
        """Карта «сущность → вид и имя места» для обхода дома.

        Локации и комнаты — **разные разделы манифеста**, и в реестре они названы
        разными словами (``локация:Улица`` против ``комната:Гостиная``): путать их
        нельзя (требование владельца 2026-10-15).

        Returns:
            Сущность → пара (вид места, имя места).
        """
        from core.models.manifest import iter_role_entities

        areas: dict[str, tuple[str, str]] = {}
        for location in getattr(self.manifest, "locations", []) or []:
            for _role, entity in iter_role_entities(location.sensors):
                areas.setdefault(entity, ("локация", location.name))
            # Приборы локации (уличные фонари, ворота, камеры) тоже в обходе:
            # пропавший прибор зоны — такая же работа для оператора, как
            # пропавший датчик (решение владельца 2026-10-18).
            for device in getattr(location, "devices", []) or []:
                areas.setdefault(device.id, ("локация", location.name))
        for room in getattr(self.manifest, "rooms", []) or []:
            for _role, entity in iter_role_entities(room.sensors):
                areas.setdefault(entity, ("комната", room.name))
            for device in getattr(room, "devices", []) or []:
                areas.setdefault(device.id, ("комната", room.name))
        return areas

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

    def _start_light_color_temperature(self) -> None:
        """Запустить службу глобальной цветовой температуры света.

        Днём свет холодный, после заката плавно теплеет к ``color_temp_warm_at``
        (по умолчанию 21:00). Служба пишет текущее значение в helper и обновляет
        горящие лампы через диспетчер: ручная блокировка и приоритеты работают
        как у остальной автоматики.

        Returns:
            Ничего.
        """
        from core.services.light_color_temperature import LightColorTemperatureService

        def _night_mode(device_id: str) -> bool:
            # Красный ночник не делаем белым. Днём автомат ночника может стоять
            # в ON_MANUAL после ручного включения — это не ночной режим, и
            # общая температура применяется как обычно.
            sleeping = getattr(getattr(self.adapter, "_ws_client", None), "asleep", None)
            for fsm_id in self.fsm.get_entities_by_device(device_id):
                if "_night_light_" not in fsm_id:
                    continue
                state = self.fsm.get_state(fsm_id)
                if state is None:
                    continue
                current = state.current_state.upper()
                if current == "ON_NIGHT":
                    return True
                if current == "ON_MANUAL" and sleeping is True:
                    return True
            return False

        service = LightColorTemperatureService(
            adapter=self.adapter,
            dispatcher=self.dispatcher,
            manifest=self.manifest,
            night_mode_supplier=_night_mode,
        )
        self._light_color_temperature = service
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Служба цветовой температуры не запущена: нет работающего цикла")
            self._light_color_temperature = None
            return
        # Ручное включение лампы: поправить оттенок сразу, не дожидаясь цикла.
        adapter = self.adapter
        if isinstance(adapter, HAAdapter):
            adapter.on_light_turned_on = service.apply_to_device
        service.start()
        logger.info(f"Цветовая температура света: {service.describe()}")

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
        self._location_mirror = create_location_mirror(
            state=self._location_state,
            rules=self.manifest.automation_rules.locations,
            adapter=adapter,
        )
        self._location_mirror.bind(self.event_bus)
        self._schedule_location_prime()

    def _platform_problems_publisher(self) -> Any | None:
        """Собрать доставку сводки проблем в дом (B79, карточка тревог).

        Карточка «Что требует внимания» на дашборде ссылается на
        ``sensor.platforma_problemy_v_dome``. Сущность создаёт зеркало платформы
        из сводки проблем (обход дома + сторож автоматов); без зеркала (дом без
        MQTT) доставки нет, и генератор дашборда эту карточку не рисует
        (`dashboard.show_platform`).

        Returns:
            Асинхронная функция ``report -> None`` либо ``None``.
        """
        rules = self.manifest.automation_rules.locations
        mirror = create_platform_mirror(rules=rules, adapter=self._adapter)
        if mirror is None:
            return None
        self._platform_mirror = mirror

        async def _publish_report(report: dict[str, Any]) -> None:
            """Пересобрать сводку и отдать её дому.

            Снимок обхода — повод пересобрать: в сводку входят ещё проблемы
            сторожа, и они меняются чаще, чем раз в полчаса.

            Args:
                report: Снимок обхода дома (не используется напрямую).

            Returns:
                Ничего.
            """
            del report
            await self._publish_problems()

        return _publish_report

    def _device_names(self) -> dict[str, str]:
        """Имена приборов манифеста: идентификатор → человеческое имя.

        Returns:
            Словарь имён.
        """
        names: dict[str, str] = {}
        places = list(self.manifest.rooms) + list(self.manifest.locations)
        for place in places:
            for device in getattr(place, "devices", []) or []:
                names[str(device.id)] = str(device.name or device.id)
        return names

    async def _publish_problems(self) -> None:
        """Опубликовать сводку проблем, если она изменилась.

        Сводка собирается из двух источников: обход дома (раз в полчаса) и
        сторож автоматов (раз в минуту). Поэтому публикация идёт по обоим
        поводам, а повтор одного и того же снимка не отправляется — иначе дом
        получал бы одинаковые сообщения каждую минуту.

        Returns:
            Ничего.
        """
        mirror = self._platform_mirror
        if mirror is None:
            return
        from core.services.problems import compose_report

        report = compose_report(
            getattr(self._house_health, "last_report", None),
            getattr(self._watchdog, "last_snapshot", None),
            device_names=self._device_names(),
            areas=self._health_areas(),
        )
        signature = (report.get("count"), tuple(report.get("problems") or []))
        if signature == self._problems_signature:
            return
        self._problems_signature = signature
        await mirror.publish_report(report)

    def _start_problems_watch(self) -> None:
        """Следить за проблемами автоматов и обновлять карточку тревог (B79).

        Обход дома идёт раз в полчаса, а зависание автомата и расхождение
        «модель ↔ прибор» сторож видит за минуты. Ждать полчаса нельзя: тревога
        должна появляться тогда, когда её заметили.

        Returns:
            Ничего.
        """
        if self._platform_mirror is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Слежение за проблемами не запущено: нет работающего цикла")
            return

        async def _watch() -> None:
            """Пересобирать сводку раз в минуту."""
            while True:
                await asyncio.sleep(60.0)
                try:
                    await self._publish_problems()
                except Exception as exc:  # noqa: BLE001 — тревога не важнее платформы
                    logger.warning(f"Сводка проблем не опубликована: {exc}")

        self._problems_task = asyncio.create_task(_watch())

    @property
    def fsm_helper_mirror(self) -> Any:
        """Зеркало состояний автоматов в помощники Home Assistant (B79).

        Returns:
            Зеркало либо ``None``, если адаптера нет.
        """
        if self._fsm_helper_mirror is None:
            from core.services.fsm_helper_mirror import FsmHelperMirror

            adapter = self._adapter
            if adapter is None:
                return None

            async def _publish_state(entity_id: str, value: str) -> bool:
                """Записать значение в помощника через Home Assistant.

                Args:
                    entity_id: Идентификатор сущности помощника.
                    value: Значение.

                Returns:
                    True, если дом принял запись.
                """
                return bool(
                    await adapter.call_service(
                        "input_text", "set_value", entity_id, {"value": value}
                    )
                )

            self._fsm_helper_mirror = FsmHelperMirror(
                send_command=getattr(adapter, "helpers_command", None),
                publish_state=_publish_state,
            )
        return self._fsm_helper_mirror

    def _start_fsm_helpers(self) -> None:
        """Создать помощников состояний и записать текущие состояния (B79).

        Помощники создаются один раз на старте: по ним дашборд показывает
        состояния автоматов, а история копится в самом доме (нативный журнал).
        Отказ дома не влияет ни на переходы, ни на журнал платформы.

        Returns:
            Ничего.
        """
        adapter = self._adapter
        mirror = self.fsm_helper_mirror
        if adapter is None or mirror is None:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Зеркало автоматов не запущено: нет работающего цикла")
            return

        async def _provision() -> None:
            """Дождаться связи, создать недостающих помощников и записать состояния."""
            for _ in range(60):
                if getattr(adapter, "is_connected", False):
                    break
                await asyncio.sleep(1.0)
            states = self.fsm.get_all_states()
            try:
                await mirror.ensure(states.keys())
            except Exception as exc:  # noqa: BLE001 — зеркало не важнее переходов
                logger.warning(f"Зеркало автоматов: помощники не созданы: {exc}")
                return
            for fsm_id, state in states.items():
                value = getattr(state, "current_state", None)
                if value:
                    await mirror.write(fsm_id, value)

        self._fsm_helper_task = asyncio.create_task(_provision())

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

    def _battery_watch_entities(self) -> list[str]:
        """Сущности заряда, за которыми следит платформа.

        Список берётся из манифеста — из роли ``battery`` комнат и локаций, — а не
        выводится из имён датчиков. Вывод по имени (``<датчик>_battery``) ошибался
        так, что наблюдение было наполовину мнимым: домен оставался от датчика,
        поэтому получались сущности, которых в доме нет
        (``binary_sensor.…_battery``, тогда как батарейка — ``sensor.…``), а сам
        список повторялся — 26 записей на 13 имён, из них 6 придуманных (боевой
        разбор 2026-10-17, B88). Дом отвечал на придуманные имена «404», и это
        стало видно только после того, как «сущности нет» перестало выглядеть как
        «не прочитали» (аудит К-5).

        Датчики вне манифеста (уличные, терраса) описаны отдельно: их батарейки
        добавляются правилами дома. Батарейки, не названные нигде, видит обход дома
        (``house_health``): он читает состояния всего дома и сообщает о низком
        заряде, поэтому без вывода по имени не теряется ничего.

        Returns:
            Сущности заряда без повторов, в порядке манифеста.
        """
        batteries: list[str] = []
        places = [*self.manifest.rooms, *(self.manifest.locations or [])]
        for place in places:
            for entity in role_entities(getattr(place, "sensors", None), "battery"):
                if entity not in batteries:
                    batteries.append(entity)

        health = self.manifest.automation_rules.sensor_health
        for entity in health.battery_watch_entities:
            if entity not in batteries:
                batteries.append(entity)
        return batteries

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

        batteries = self._battery_watch_entities()
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
        """Часовой пояс дома из метаданных экземпляра.

        Returns:
            ``ZoneInfo`` дома либо пояс процесса, если не задан.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        name = getattr(self.manifest.instance, "time_zone", None)
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
