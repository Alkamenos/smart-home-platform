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
    """

    def __init__(
        self,
        adapter: Any,
        areas: dict[str, tuple[str, str]] | None = None,
        stale_after_sec: float = DEFAULT_STALE_AFTER_SEC,
        low_battery_percent: float = DEFAULT_LOW_BATTERY_PERCENT,
        interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
        clock: Any | None = None,
    ) -> None:
        self._adapter = adapter
        self.areas = dict(areas or {})
        self.stale_after_sec = stale_after_sec
        self.low_battery_percent = low_battery_percent
        self.interval_minutes = interval_minutes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._task: asyncio.Task[None] | None = None
        self._report: dict[str, Any] | None = None

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
        for item in states:
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str):
                continue
            if not self._is_sensor(entity_id, item):
                continue
            reading = self._reading(entity_id, item, now)
            kind, name = self.areas.get(entity_id, ("без места", ""))
            areas.setdefault(self._area_title(kind, name), []).append(reading)
            problem = self._problem(reading)
            if problem is not None:
                problems.append(problem)
        self._report = {
            "generated_at": now.isoformat(),
            "problems": problems,
            "areas": areas,
            "sensor_count": sum(len(items) for items in areas.values()),
        }
        return self._report

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
        return {
            "entity_id": entity_id,
            "name": str(attributes.get("friendly_name") or entity_id),
            "value": item.get("state"),
            "unit": attributes.get("unit_of_measurement"),
            "device_class": attributes.get("device_class"),
            "area_kind": kind,
            "area": name,
            "at": updated.isoformat() if updated else None,
            "age_sec": round(age, 1) if age is not None else None,
            "stale": age is not None and age > self.stale_after_sec,
        }

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
            return self._named(PROBLEM_STALE, reading, f"молчит {hours} ч")
        battery = self._battery_percent(reading)
        if battery is not None and battery < self.low_battery_percent:
            return self._named(PROBLEM_LOW_BATTERY, reading, f"заряд {battery:g} %")
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

    def _battery_percent(self, reading: dict[str, Any]) -> float | None:
        """Заряд батарейки числом, если это батарейка.

        Args:
            reading: Запись показания.

        Returns:
            Проценты либо ``None``.
        """
        if str(reading.get("device_class") or "") != "battery" and not str(
            reading.get("entity_id") or ""
        ).endswith(BATTERY_SUFFIX):
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
