"""House services for the composition root (spec 018, T059).

Extracted from Container: health, problems, locations, helpers and auxiliary
services that run alongside the core.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from loguru import logger

from adapters.ha_adapter import HAAdapter
from app.factories import create_event_store, create_location_mirror, create_platform_mirror
from core.models.manifest import role_entities


def light_automation_on(engine: Any, device_id: str) -> bool:
    """Разрешает ли автоматика держать лампу включённой.

    Служба общей цветовой температуры обходит «горящие» лампы по факту и
    отправляет ``turn_on`` с температурой. Если автомат уже решил «выключено»,
    такая команда зажигает погашенный свет (живая находка 2026-11-08: кровать
    после включения «мы спим»). Поэтому решение спрашивается у движка: лампа
    участвует, только когда хотя бы один её автомат не в ``OFF*``.

    Args:
        engine: Движок автоматов.
        device_id: Сущность лампы.

    Returns:
        True, если лампу можно трогать. Если автоматов у прибора нет, поведение
        прежнее — служба решает по фактическому состоянию.
    """
    get_fsms = getattr(engine, "get_entities_by_device", None)
    get_state = getattr(engine, "get_state", None)
    if not callable(get_fsms) or not callable(get_state):
        return True
    current = [
        state.current_state.upper()
        for fsm_id in get_fsms(device_id)
        if (state := get_state(fsm_id)) is not None
    ]
    if not current:
        return True
    return any(not name.startswith("OFF") for name in current)


class ContainerHouseMixin:
    """Wire health, problem, location and helper services."""

    _ventilation_watchdog: Any
    _light_color_temperature: Any
    _house_health: Any
    _problem_registry: Any
    _helper_cleanup: Any
    _location_state: Any
    _location_prime_task: Any
    _location_mirror: Any
    _platform_mirror: Any
    _problems_signature: Any
    _problems_task: Any
    _fsm_helper_mirror: Any
    _fsm_helper_task: Any
    _ac_protection: Any
    _sensor_health: Any

    @property
    def problem_registry(self) -> Any:
        """Реестр проблем дома: first_seen, закрытые и уведомления.

        Создаётся один раз и переживает перезапуск: файл
        ``health_problems.json`` в DATA_PATH. Пустой файл — нормальный первый
        запуск.

        Returns:
            Реестр проблем.
        """
        if self._problem_registry is None:
            from core.persistence.health_store import HealthStore
            from core.services.health_registry import HealthRegistry

            self._problem_registry = HealthRegistry(HealthStore())
        return self._problem_registry

    @property
    def house_health(self) -> Any:
        """Обход дома: проблемы и реестр показаний (BACKLOG F6).

        Создаётся при сборке и читается веб-слоем: интерфейсу нужен последний
        снимок — проблемы всех датчиков дома, а не только приборов манифеста.

        Returns:
            Служба обхода.
        """
        if self._house_health is None:
            from core.services.health_expectations import HealthExpectations
            from core.services.house_health import (
                DEFAULT_LOW_BATTERY_PERCENT,
                DEFAULT_STALE_AFTER_SEC,
                HouseHealthService,
            )

            rules = getattr(self.manifest.automation_rules, "sensor_health", None)
            stale_hours = getattr(rules, "stale_min_hours", None)
            stale_min_hours = float(stale_hours) if isinstance(stale_hours, (int, float)) else 2.0
            stale_after = (
                stale_min_hours * 3600.0
                if isinstance(stale_hours, (int, float))
                else DEFAULT_STALE_AFTER_SEC
            )
            low_battery = getattr(rules, "battery_low_percent", None)
            battery_silent = getattr(rules, "battery_silent_hours", None)
            interval = getattr(rules, "check_interval_minutes", None)
            self._house_health = HouseHealthService(
                adapter=self.adapter,
                areas=self._health_areas(),
                battery_types=dict(getattr(self.manifest, "battery_types", {}) or {}),
                stale_after_sec=stale_after,
                low_battery_percent=(
                    float(low_battery)
                    if isinstance(low_battery, (int, float))
                    else DEFAULT_LOW_BATTERY_PERCENT
                ),
                interval_minutes=(float(interval) if isinstance(interval, (int, float)) else 30.0),
                registry=self.problem_registry,
                expectations=HealthExpectations(
                    event_store=create_event_store(),
                    stale_min_sec=stale_min_hours * 3600.0,
                ),
                stale_min_hours=stale_min_hours,
                battery_silent_hours=(
                    float(battery_silent) if isinstance(battery_silent, (int, float)) else 48.0
                ),
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

        def _automation_on(device_id: str) -> bool:
            # Поддержание температуры не зажигает лампу, которую автомат погасил.
            return light_automation_on(self.fsm, device_id)

        service = LightColorTemperatureService(
            adapter=self.adapter,
            dispatcher=self.dispatcher,
            manifest=self.manifest,
            night_mode_supplier=_night_mode,
            automation_on_supplier=_automation_on,
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
            registry=self.problem_registry,
        )
        signature = (report.get("count"), tuple(report.get("problems") or []))
        if signature == self._problems_signature:
            return
        self._problems_signature = signature
        await mirror.publish_report(report)

    def problems_snapshot(self) -> dict[str, Any]:
        """Единый снимок проблем для API и страницы.

        Обход и сторож сводятся в один список, реестр дополняет его историей:
        ``first_seen``, уровни и причины одной сущности в одной группе.

        Returns:
            Снимок с ``generated_at``, ``count``, ``levels`` и ``problems``.
        """
        from core.services.problems import compose_report

        report = compose_report(
            getattr(self._house_health, "last_report", None),
            getattr(self._watchdog, "last_snapshot", None),
            device_names=self._device_names(),
            areas=self._health_areas(),
            registry=self.problem_registry,
        )
        snapshot = self.problem_registry.snapshot()
        snapshot["generated_at"] = report.get("generated_at")
        return snapshot

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
