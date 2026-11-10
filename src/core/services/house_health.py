"""Обход дома: что сломалось, что молчит, что на исходе (BACKLOG F6).

Задача владельца (2026-10-15): «система должна считывать все возможные сенсоры по
локациям и комнатам — что-то вроде машинного зрения для ИИ», плюс обход дома с
сообщением о проблемах.

Отсюда две выдачи, и их нельзя смешивать:

* **реестр показаний** (`areas`) — всё, что дом отдаёт, сгруппированное по
  локациям и комнатам манифеста. Локации и комнаты **намеренно названы разными
  видами** (`комната:Гостиная` против `локация:Улица`): это разные сущности
  манифеста, и путать их нельзя. Служит чтением для ИИ и человека.
* **проблемы** (`problems`) — только то, что требует внимания: прибор не отвечает,
  показание устарело, батарейка на исходе. Проблемы ограничены «датчиковыми»
  сущностями: дом импортирует полторы тысячи сущностей, и «проблема» в каждой
  служебной кнопке утопила бы тревоги.

Молчание — отдельное наблюдаемое состояние (``stale``), а не согласие
(концепция §7, п. 4): датчик, который не обновлялся дольше порога, называется
молчащим, а не «всё в порядке».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from core.logger import get_logger


logger = get_logger(__name__)


#: Классы датчиков, по которым дом сообщает о проблемах. Служебные сущности
#: (update, button, automation, script и прочее) в обход не попадают: их
#: «недоступность» не требует вмешательства, а тревоги утопила бы.
SENSOR_DEVICE_CLASSES = frozenset(
    {
        "temperature",
        "humidity",
        "motion",
        "occupancy",
        "presence",
        "contact",
        "illuminance",
        "pressure",
        "wind_speed",
        "rain",
        "battery",
        "power",
        "voltage",
        "current",
        "carbon_dioxide",
        "pm25",
        "soil_moisture",
        "water",
        "smoke",
        "gas",
        "door",
        "window",
    }
)

#: Классы датчиков, которые **сами** шлют показания regularly. Только у них
#: молчание означает проблему: датчик движения или контакт окна молчит по
#: нескольку суток, и это норма — «молчит» для них означало бы сотни ложных
#: тревог (их свежесть уже считается снимком локаций по правилам манифеста).
ACTIVELY_REPORTING_CLASSES = frozenset(
    {
        "temperature",
        "humidity",
        "illuminance",
        "pressure",
        "wind_speed",
        "rain",
        "carbon_dioxide",
        "pm25",
        "soil_moisture",
        "water",
    }
)

#: Признак «это батарейка» по имени сущности: у части датчиков класс не выставлен.
BATTERY_SUFFIX = "_battery"

PROBLEM_UNAVAILABLE = "unavailable"
PROBLEM_STALE = "stale"
PROBLEM_LOW_BATTERY = "low_battery"
PROBLEM_BATTERY_SILENT = "battery_silent"

#: Дом не прочитался: обход не состоялся.
#:
#: Отдельная проблема, а не пустой список. «Проблем нет» и «не смогли прочитать» —
#: разные вещи, и путать их значит врать в панели тревог: инструмент наблюдаемости
#: докладывал «всё хорошо», когда датчики не читались вовсе (аудит 2026-10-16, К-3).
PROBLEM_HOUSE_UNREADABLE = "house_unreadable"

#: Сущность манифеста, которой нет в доме.
#:
#: Обход перебирает то, что **отдал** Home Assistant, поэтому сущность манифеста,
#: которой в доме нет (опечатка в имени или снятый прибор), не попадала ни в
#: реестр, ни в тревоги: сбой выглядел как норма. Место из манифеста известно,
#: поэтому отсутствие называется, а не умалчивается (аудит 2026-10-16, К-5).
#:
#: Касается и датчиков, и приборов комнат: и те и другие описаны в манифесте
#: (``Container._health_areas``), и прибор, которого в доме нет, — такая же работа
#: для оператора, как пропавший датчик.
PROBLEM_MISSING_ENTITY = "missing_entity"

#: Дольше этого показание считается молчащим. Шесть часов: раз в сутки значения
#: обновляют даже медленные датчики, а суточные пороги террасы не трогаем.
DEFAULT_STALE_AFTER_SEC = 6 * 3600

#: Ниже этого заряда батарейка считается на исходе.
DEFAULT_LOW_BATTERY_PERCENT = 20.0

#: Как часто обходить дом, если ничего не произошло.
DEFAULT_INTERVAL_MINUTES = 30.0


class HouseHealthService:
    """Обходить дом и отвечать: что сломалось, что молчит, что на исходе.

    Args:
        adapter: Адаптер Home Assistant: отдаёт состояния всех сущностей.
        areas: Сущность → вид и имя места (``("комната", "Гостиная")``). Строится
            из манифеста: локации и комнаты — разные разделы, и путать их нельзя.
        stale_after_sec: Через сколько секунд показание считается молчащим.
        low_battery_percent: Порог заряда, ниже которого батарейка «на исходе».
        interval_minutes: Как часто обходить дом.
        clock: Источник времени; подменяется в тестах.
        on_report: Кому отдать снимок обхода (зеркало проблем в Home Assistant).
            Отказ подписчика не отменяет обход: публикация в MQTT — доставка, а
            не условие работы.
        registry: Реестр проблем: сохраняет историю и first_seen. Необязателен,
            чтобы старые тесты и локальный запуск без файла работали.
        expectations: Расчёт ожидаемого интервала датчика. Если не задан,
            действует общий порог ``stale_after_sec``.
        stale_min_hours: Минимальный порог молчания, часов.
        battery_silent_hours: Сколько часов без отчёта о заряде считать
            молчанием батарейки.
        command_expectations: Трекер ожиданий применения команд.
        command_grace_minutes: Сколько минут ждать применения команды.
    """

    def __init__(
        self,
        adapter: Any,
        areas: dict[str, tuple[str, str]] | None = None,
        battery_types: dict[str, str] | None = None,
        stale_after_sec: float = DEFAULT_STALE_AFTER_SEC,
        low_battery_percent: float = DEFAULT_LOW_BATTERY_PERCENT,
        interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
        clock: Any | None = None,
        on_report: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        registry: Any | None = None,
        expectations: Any | None = None,
        stale_min_hours: float = 2.0,
        battery_silent_hours: float = 48.0,
        command_expectations: Any | None = None,
        command_grace_minutes: float = 5.0,
    ) -> None:
        self._adapter = adapter
        self.areas = dict(areas or {})
        self.battery_types = dict(battery_types or {})
        self.stale_after_sec = stale_after_sec
        self.low_battery_percent = low_battery_percent
        self.interval_minutes = interval_minutes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None
        self._report: dict[str, Any] | None = None
        self._on_report = on_report
        self._registry = registry
        self._expectations = expectations
        self._stale_min_sec = max(0.0, float(stale_min_hours) * 3600.0)
        self.battery_silent_hours = max(1.0, float(battery_silent_hours))
        self._command_expectations = command_expectations
        self._command_grace_minutes = max(0.0, float(command_grace_minutes))

    @property
    def last_report(self) -> dict[str, Any] | None:
        """Последний снимок обхода (для интерфейса и тревог).

        Returns:
            Снимок либо ``None``, если обход ещё не проходил.
        """
        return self._report

    def start(self) -> bool:
        """Запустить обход по времени.

        Returns:
            True, если обход запущен; False — нет цикла событий.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Обход дома не запущен: нет цикла событий")
            return False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return True

    async def stop(self) -> None:
        """Остановить обход.

        Returns:
            Ничего.
        """
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — остановка не шумит
                return

    async def sweep(self) -> dict[str, Any]:
        """Обойти дом один раз.

        Returns:
            Снимок: ``generated_at``, ``problems`` (что требует внимания) и
            ``areas`` (реестр показаний по локациям и комнатам).
        """
        states = await self._read_states()
        now = self._clock()
        problems: list[dict[str, Any]] = []
        areas: dict[str, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        if not states:
            # Дом не прочитался — это и есть проблема, и она обязана быть названа.
            # Прежде отчёт отдавал пустой список проблем, и панель тревог молчала:
            # «в доме порядок» было неотличимо от «не смогли прочитать» (К-3).
            problems.append(
                {
                    "kind": PROBLEM_HOUSE_UNREADABLE,
                    "subject": None,
                    "name": "Дом",
                    "area": "",
                    "detail": (
                        "состояния Home Assistant не прочитаны: обход дома не состоялся, "
                        "поэтому отсутствие тревог здесь не значит, что всё хорошо"
                    ),
                    "value": None,
                    "at": now.isoformat(),
                }
            )
        for item in states:
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            seen.add(entity_id)
            if not self._is_sensor(entity_id, item):
                continue
            reading = self._reading(entity_id, item, now)
            kind, name = self.areas.get(entity_id, ("без места", ""))
            areas.setdefault(self._area_title(kind, name), []).append(reading)
            problem = self._problem(reading)
            if problem is not None:
                problems.append(problem)
        if states and self._command_expectations is not None:
            problems.extend(self._command_problems(states, now))
        if states:
            # Сущности, которых дом не отдал. Только когда дом вообще отвечал:
            # иначе пустой ответ превращался бы в тревогу на каждую сущность
            # манифеста, и настоящие проблемы в них утонули бы.
            #
            # Оговорка честности: «не отдал» — наблюдение, а не приговор.
            # Home Assistant, перезапускаясь, отдаёт неполный список (интеграции
            # загружаются постепенно), поэтому сразу после его старта возможна
            # разовая пачка таких записей — следующий обход её снимет. Обещать
            # «сущности нет» сильнее наблюдаемого мы не станем.
            for entity_id, (kind, name) in self.areas.items():
                if entity_id not in seen:
                    problems.append(self._missing_problem(entity_id, kind, name, now))
        self._report = {
            "generated_at": now.isoformat(),
            "problems": problems,
            "areas": areas,
            "sensor_count": sum(len(items) for items in areas.values()),
            "readable": bool(states),
        }
        if self._registry is not None:
            try:
                self._registry.observe_report(
                    problems,
                    now.isoformat(),
                    source="health",
                    close_missing=bool(states),
                )
            except Exception as exc:  # noqa: BLE001 — история не отменяет обход
                logger.warning(f"Обход дома: реестр проблем не обновлён: {exc}")
        await self._notify(self._report)
        return self._report

    async def _notify(self, report: dict[str, Any]) -> None:
        """Отдать снимок обхода подписчику, не роняя обход при отказе (FR-009).

        Args:
            report: Снимок обхода.

        Returns:
            Ничего.
        """
        if self._on_report is None:
            return
        try:
            await self._on_report(report)
        except Exception as exc:  # noqa: BLE001 — доставка не отменяет обход
            logger.warning(f"Обход дома: снимок не доставлен: {exc}")

    async def _read_states(self) -> list[dict[str, Any]]:
        """Прочитать состояния всех сущностей.

        Returns:
            Список состояний; пустой, если связи нет.
        """
        reader = getattr(self._adapter, "get_all_states", None)
        if not callable(reader):
            return []
        try:
            raw = await reader()
        except Exception as exc:  # noqa: BLE001 — обход не должен падать
            logger.warning(f"Обход дома: состояния не прочитаны: {exc}")
            return []
        return [item for item in raw or [] if isinstance(item, dict)]

    def _is_sensor(self, entity_id: str, item: dict[str, Any]) -> bool:
        """Считать ли сущность датчиком: по классу прибора или по имени.

        Args:
            entity_id: Идентификатор сущности.
            item: Состояние сущности.

        Returns:
            True, если сущность — датчик.
        """
        attributes = item.get("attributes") or {}
        device_class = str(attributes.get("device_class") or "").lower()
        if device_class in SENSOR_DEVICE_CLASSES:
            return True
        return entity_id.endswith(BATTERY_SUFFIX)

    def _reading(self, entity_id: str, item: dict[str, Any], now: datetime) -> dict[str, Any]:
        """Собрать показание датчика для реестра.

        Args:
            entity_id: Идентификатор сущности.
            item: Состояние сущности.
            now: Текущее время.

        Returns:
            Запись показания: значение, единица, время и признаки.
        """
        attributes = item.get("attributes") or {}
        updated = self._parse_time(item.get("last_updated") or item.get("last_changed"))
        age = None if updated is None else (now - updated).total_seconds()
        kind, name = self.areas.get(entity_id, ("без места", ""))
        device_class = attributes.get("device_class")
        expectation = None
        if self._expectations is not None:
            try:
                expectation = self._expectations.expectation(
                    entity_id,
                    device_class,
                    now_ts=now.timestamp(),
                )
            except Exception:  # noqa: BLE001 — ожидание не отменяет обход
                expectation = None
        threshold = expectation.stale_after_sec if expectation is not None else self.stale_after_sec
        threshold = max(float(threshold), self._stale_min_sec)
        return {
            "entity_id": entity_id,
            "name": str(attributes.get("friendly_name") or entity_id),
            "value": item.get("state"),
            "unit": attributes.get("unit_of_measurement"),
            "device_class": device_class,
            "area_kind": kind,
            "area": name,
            "battery_type": self.battery_types.get(entity_id),
            "at": updated.isoformat() if updated else None,
            "age_sec": round(age, 1) if age is not None else None,
            "stale": age is not None and age > threshold,
            "stale_after_sec": round(threshold, 1),
            "expected_interval_sec": (
                round(expectation.expected_interval_sec, 1) if expectation is not None else None
            ),
            "expectation_source": expectation.source if expectation is not None else None,
        }

    def _command_problems(
        self, states: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        """Проверить, применились ли отправленные команды.

        Ожидание создаёт диспетчер в момент успешного вызова Home Assistant.
        Здесь оно сверяется с фактическим состоянием прибора: совпало — команда
        применена; прошло больше допуска, а состояние другое — проблема.
        Переходные состояния (штора едет, прибор недоступен) не считаются
        провалом: ждём дальше или отдаём эту причину другим проверкам.

        Args:
            states: Состояния сущностей из текущего обхода.
            now: Время обхода.

        Returns:
            Список проблем ``command_not_applied``.
        """
        tracker = self._command_expectations
        if tracker is None:
            return []
        by_entity: dict[str, Any] = {}
        names: dict[str, str] = {}
        for item in states:
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            by_entity[entity_id] = item.get("state")
            attributes = item.get("attributes") or {}
            names[entity_id] = str(attributes.get("friendly_name") or entity_id)
        problems: list[dict[str, Any]] = []
        grace_sec = self._command_grace_minutes * 60.0
        for expectation in tracker.pending(now.timestamp()):
            if expectation.age_sec(now.timestamp()) < grace_sec:
                continue
            actual = by_entity.get(expectation.device_id)
            if actual is None:
                tracker.clear(expectation.device_id)
                continue
            if tracker.is_applied(expectation, actual):
                tracker.clear(expectation.device_id)
                continue
            if tracker.is_transitional(actual):
                if str(actual).lower() in ("unavailable", "unknown"):
                    tracker.clear(expectation.device_id)
                continue
            area = self.areas.get(expectation.device_id, ("", ""))[1]
            problem = tracker.problem(
                expectation,
                actual=actual,
                area=area,
                name=names.get(expectation.device_id, expectation.device_id),
                now=now.timestamp(),
            )
            problems.append(problem)
            # Ожидание не снимаем: проблема должна жить, пока прибор не
            # покажет нужное состояние (наблюдатель состояния) или пока не
            # истечёт TTL. Иначе она закрывалась бы через минуту, и владелец
            # видел бы только мигание уведомления.
        return problems

    def _problem(self, reading: dict[str, Any]) -> dict[str, Any] | None:
        """Требует ли показание внимания.

        Args:
            reading: Запись показания.

        Returns:
            Проблема либо ``None``.
        """
        # Тревоги — только о приборах дома: их места описаны в манифесте
        # (локации и комнаты). Всё прочее, что импортировано из Home Assistant
        # (телефоны, прогнозы, служебные шаблоны), остаётся в реестре показаний
        # для чтения, но «проблемой дома» не объявляется: иначе тревог было бы
        # 82 из 139 датчиков, и настоящие в них утонули бы.
        if reading.get("area_kind") == "без места":
            return None
        value = str(reading.get("value") or "").lower()
        if value in ("unavailable", "unknown", "none", ""):
            return self._named(PROBLEM_UNAVAILABLE, reading, "датчик не отвечает")
        if reading.get("stale") and self._reports_by_itself(reading):
            hours = round(float(reading.get("age_sec") or 0) / 3600, 1)
            expected = reading.get("expected_interval_sec")
            if isinstance(expected, (int, float)) and expected > 0:
                waiting = f"{expected / 3600:g} ч" if expected >= 3600 else f"{expected / 60:g} мин"
                detail = f"молчит {hours} ч при ожидании {waiting}"
            else:
                detail = f"молчит {hours} ч"
            return self._named(PROBLEM_STALE, reading, detail)
        battery = self._battery_percent(reading)
        if battery is not None and battery < self.low_battery_percent:
            kind = self.battery_types.get(str(reading.get("entity_id") or ""))
            need = f" — нужна {kind}" if kind else ""
            return self._named(PROBLEM_LOW_BATTERY, reading, f"заряд {battery:g} %{need}")
        if self._is_battery(reading):
            age_sec = float(reading.get("age_sec") or 0)
            if age_sec > self.battery_silent_hours * 3600.0:
                ages = round(age_sec / 3600.0, 1)
                return self._named(
                    PROBLEM_BATTERY_SILENT,
                    reading,
                    f"батарейка не отчитывалась {ages} ч",
                )
        return None

    def _reports_by_itself(self, reading: dict[str, Any]) -> bool:
        """Шлёт ли датчик показания сам: у таких молчание — проблема.

        Args:
            reading: Запись показания.

        Returns:
            True, если молчание датчика требует внимания.
        """
        # Батарейки сюда не входят: у них здоровье — это **заряд**, а не
        # регулярность. Батарейные датчики Zigbee отчитываются раз в сутки и
        # реже, и «молчит 89 часов» про батарейку — норма, а не проблема.
        device_class = str(reading.get("device_class") or "").lower()
        return device_class in ACTIVELY_REPORTING_CLASSES

    def _is_battery(self, reading: dict[str, Any]) -> bool:
        """Является ли показание зарядом батарейки.

        Args:
            reading: Запись показания.

        Returns:
            True, если это батарейка.
        """
        if str(reading.get("device_class") or "") == "battery":
            return True
        return str(reading.get("entity_id") or "").endswith(BATTERY_SUFFIX)

    def _battery_percent(self, reading: dict[str, Any]) -> float | None:
        """Заряд батарейки числом, если это батарейка.

        Args:
            reading: Запись показания.

        Returns:
            Проценты либо ``None``.
        """
        if not self._is_battery(reading):
            return None
        raw = reading.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _named(self, kind: str, reading: dict[str, Any], detail: str) -> dict[str, Any]:
        """Собрать запись проблемы.

        Args:
            kind: Вид проблемы.
            reading: Запись показания.
            detail: Объяснение человеческим языком.

        Returns:
            Запись проблемы.
        """
        where = reading.get("area") or "без места"
        return {
            "kind": kind,
            "subject": reading.get("entity_id"),
            "name": reading.get("name"),
            "area": where,
            "detail": f"{reading.get('name')} ({where}): {detail}",
            "value": reading.get("value"),
            "at": reading.get("at"),
        }

    def _missing_problem(
        self, entity_id: str, kind: str, name: str, now: datetime
    ) -> dict[str, Any]:
        """Проблема «сущность манифеста, которой нет в доме».

        Args:
            entity_id: Идентификатор сущности из манифеста.
            kind: Вид места (``комната`` или ``локация``).
            name: Имя места.
            now: Текущее время.

        Returns:
            Запись проблемы.
        """
        where = name or "без места"
        return {
            "kind": PROBLEM_MISSING_ENTITY,
            "subject": entity_id,
            "name": entity_id,
            "area": where,
            "detail": (
                f"{entity_id} ({where}): сущности нет в доме — манифест ссылается "
                f"на неё, а Home Assistant её не отдал"
            ),
            "value": None,
            "at": now.isoformat(),
        }

    def _area_title(self, kind: str, name: str) -> str:
        """Название группы показаний.

        Локация и комната — разные разделы манифеста, и в реестре они названы
        разными словами: «локация:Улица» и «комната:Гостиная». Путать их нельзя
        (требование владельца 2026-10-15).

        Args:
            kind: Вид места (``комната``, ``локация`` или ``без места``).
            name: Имя места.

        Returns:
            Название группы.
        """
        if not name:
            return "без места"
        return f"{kind}:{name}"

    def _parse_time(self, raw: Any) -> datetime | None:
        """Разобрать время Home Assistant.

        Args:
            raw: Строка ISO-8601.

        Returns:
            Время с часовым поясом либо ``None``.
        """
        if not isinstance(raw, str) or not raw:
            return None
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)

    async def _run(self) -> None:
        """Обходить дом до остановки."""
        interval = max(self.interval_minutes, 0.1) * 60.0
        delay = min(60.0, interval)
        while True:
            await asyncio.sleep(delay)
            delay = interval
            try:
                report = await self.sweep()
                logger.info(
                    f"Обход дома: датчиков {report['sensor_count']}, "
                    f"проблем {len(report['problems'])}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — фоновый обход не умирает
                logger.warning(f"Обход дома не удался: {exc}")
