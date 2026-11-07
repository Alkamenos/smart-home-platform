"""Platform service lifecycle for the composition root (spec 018, T059).

Extracted from Container: starting, wiring and stopping application services is
a lifecycle concern, separate from lazy component creation.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
from datetime import datetime as dt_datetime, time as dt_time
from typing import Any

from loguru import logger


class ContainerLifecycleMixin:
    """Start and wire application services after the core is built."""

    _day_cycle: Any
    _deco_watcher: Any
    _ventilation_watchdog: Any
    _light_color_temperature: Any
    _house_health: Any
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
