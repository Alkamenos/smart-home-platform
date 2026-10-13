"""Снимок состояния локаций: сбор из событий шины и производные (спека 016).

Сервис отвечает на вопрос «что сейчас известно о локации»: держит последнее
показание каждого привязанного датчика с временем, единицей и признаком
доступности и собирает по запросу снимок с производными.

Откуда берутся показания: события ``state_change``, которые публикует адаптер
после фильтра подписки (``collect_subscribed_entities``). Поэтому датчики особых
зон (улица, грядки) обязаны быть в манифесте: без них подписка их не отдаст.

Почему сервис, а не «поле в автомате»: датчики привязаны к локации, а не к
устройству. Движение в спальне интересует и светильник, и наблюдение за домом;
хранить «последнее показание» в автомате светильника значило бы, что снимка
спальни не будет, если светильник убрали из манифеста.

Производные считаются на чтение (research.md D6): отдельного планировщика нет,
и производная всегда согласована с сохранёнными показаниями.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from core.events.event_router import as_measurement
from core.models.location import (
    LocationSnapshot,
    SensorReading,
    build_snapshot,
)
from core.models.manifest import Manifest


#: Имя события шины, которое публикует адаптер на каждое изменение состояния.
#: То же имя читает мост журнала (``services/fsm_state_bridge.py``).
EVENT_STATE_CHANGE = "state_change"

#: Значения, которые считаются «включено»: нужно, чтобы запомнить время
#: последнего срабатывания датчика движения (сам он быстро возвращается в off).
ON_VALUES = frozenset({"on", "true", "1", "open", "opened", "detected"})


class _LocationDefinition:
    """Внутреннее описание локации: кто это и какие у неё датчики.

    Args:
        location_id: Идентификатор локации.
        name: Человекочитаемое имя.
        kind: Вид зоны (``room``, ``outdoor``, ``garden``).
        stale_after_sec: Порог молчания локации.
        sensors: Роль датчика → сущность.
    """

    def __init__(
        self,
        *,
        location_id: str,
        name: str,
        kind: str,
        stale_after_sec: int,
        sensors: dict[str, str],
    ) -> None:
        self.id = location_id
        self.name = name
        self.kind = kind
        self.stale_after_sec = stale_after_sec
        self.sensors = sensors


class LocationStateService:
    """Держит последние показания датчиков и собирает снимки локаций.

    Args:
        manifest: Манифест дома: комнаты и особые зоны (``locations``).
        unit_provider: Как узнать единицу измерения сущности (обычно
            ``adapter.get_entity_unit``). Без него единицы будут пустыми, но
            снимок собирается.
    """

    def __init__(
        self,
        manifest: Manifest,
        *,
        unit_provider: Callable[[str], str | None] | None = None,
        state_reader: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._manifest = manifest
        self._unit_provider = unit_provider
        self._state_reader = state_reader
        self._rules = manifest.automation_rules.locations
        self._locations: dict[str, _LocationDefinition] = {}
        #: Сущность → [(локация, роль)]: один датчик бывает привязан к двум
        #: локациям (движение гостиной и влажность для вентиляции кабинета).
        self._roles_by_entity: dict[str, list[tuple[str, str]]] = {}
        #: Локация → сущность → последнее показание.
        self._readings: dict[str, dict[str, SensorReading]] = {}
        self._build()

    # ------------------------------------------------------------------
    # Сборка описания локаций
    # ------------------------------------------------------------------

    def _build(self) -> None:
        """Собрать локации из манифеста: комнаты и особые зоны."""
        for room in self._manifest.rooms:
            self._add_location(
                location_id=room.id,
                name=room.name,
                kind="room",
                stale_after_sec=self._rules.stale_after_sec,
                sensors=dict(room.sensors or {}),
            )

        for location in self._manifest.locations:
            if location.id in self._locations:
                logger.warning(
                    f"Локация '{location.id}' описана дважды (комната и особая зона): "
                    "берётся первая"
                )
                continue
            self._add_location(
                location_id=location.id,
                name=location.name,
                kind=location.kind,
                stale_after_sec=location.stale_after_sec or self._rules.stale_after_sec,
                sensors=dict(location.sensors or {}),
            )

    def _add_location(
        self,
        *,
        location_id: str,
        name: str,
        kind: str,
        stale_after_sec: int,
        sensors: dict[str, str],
    ) -> None:
        """Добавить локацию и запомнить её датчики.

        Args:
            location_id: Идентификатор локации.
            name: Имя локации.
            kind: Вид зоны.
            stale_after_sec: Порог молчания.
            sensors: Роль → сущность.

        Returns:
            Ничего.
        """
        self._locations[location_id] = _LocationDefinition(
            location_id=location_id,
            name=name,
            kind=kind,
            stale_after_sec=stale_after_sec,
            sensors=sensors,
        )
        self._readings.setdefault(location_id, {})
        for role, entity_id in sensors.items():
            if not entity_id:
                continue
            self._roles_by_entity.setdefault(entity_id, []).append((location_id, role))

    # ------------------------------------------------------------------
    # Приём показаний
    # ------------------------------------------------------------------

    def subscribe(self, event_bus: Any) -> None:
        """Подписаться на изменения состояний.

        Args:
            event_bus: Шина событий платформы.

        Returns:
            Ничего.
        """
        event_bus.subscribe(EVENT_STATE_CHANGE, self.on_state_change)
        logger.info(f"Наблюдение за локациями: {self.describe()}")

    async def on_state_change(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Запомнить показание датчика, если он привязан к локации.

        Args:
            event_type: Имя события (не используется).
            payload: Полезная нагрузка изменения состояния.
            trace_id: Идентификатор трассы (не используется).

        Returns:
            Ничего.
        """
        del event_type, trace_id
        entity_id = (payload or {}).get("entity_id")
        value = (payload or {}).get("new_state")
        if not entity_id or value is None:
            return
        roles = self._roles_by_entity.get(entity_id)
        if not roles:
            return
        self.record(entity_id, value)

    def record(self, entity_id: str, value: Any, *, at: datetime | None = None) -> None:
        """Записать показание датчика во все локации, где он привязан.

        Args:
            entity_id: Сущность Home Assistant.
            value: Значение состояния.
            at: Время показания; по умолчанию — сейчас.

        Returns:
            Ничего.
        """
        moment = at or datetime.now(UTC)
        text = str(value).strip()
        reading_value = as_measurement(value) if text else value
        is_on = text.lower() in ON_VALUES

        for location_id, role in self._roles_by_entity.get(entity_id, []):
            previous = self._readings[location_id].get(entity_id)
            # Время последнего «включено» переживает возврат в off: датчик
            # движения срабатывает и сразу гаснет, а «человек ушёл пять минут
            # назад» считается по последнему срабатыванию.
            last_on_at = moment if is_on else (previous.last_on_at if previous else None)
            self._readings[location_id][entity_id] = SensorReading(
                entity_id=entity_id,
                role=role,
                value=reading_value,
                unit=self._unit_of(entity_id),
                at=moment,
                available=text.lower() not in ("unavailable", "unknown", ""),
                last_on_at=last_on_at,
            )

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def location_ids(self) -> list[str]:
        """Идентификаторы всех локаций.

        Returns:
            Список идентификаторов в порядке манифеста.
        """
        return list(self._locations)

    def locations(self) -> list[dict[str, Any]]:
        """Краткое описание локаций: кто это и сколько датчиков.

        Returns:
            Список словарей с ``id``, ``name``, ``kind`` и ``sensor_count``.
        """
        return [
            {
                "id": location.id,
                "name": location.name,
                "kind": location.kind,
                "sensor_count": len(location.sensors),
            }
            for location in self._locations.values()
        ]

    def snapshot(self, location_id: str, *, now: datetime | None = None) -> LocationSnapshot | None:
        """Собрать снимок локации.

        Args:
            location_id: Идентификатор локации.
            now: Момент чтения (для тестов и для согласованных снимков).

        Returns:
            Снимок либо ``None``, если локации нет в манифесте.
        """
        location = self._locations.get(location_id)
        if location is None:
            return None
        return build_snapshot(
            location_id=location.id,
            name=location.name,
            kind=location.kind,
            readings=list(self._readings.get(location_id, {}).values()),
            now=now or datetime.now(UTC),
            stale_after_sec=location.stale_after_sec,
            presence_window_sec=self._rules.presence_window_sec,
        )

    def sensor_entities(self, location_id: str) -> list[str]:
        """Сущности датчиков локации — для запроса её истории.

        Args:
            location_id: Идентификатор локации.

        Returns:
            Список сущностей (пустой, если локации нет).
        """
        location = self._locations.get(location_id)
        if location is None:
            return []
        return sorted(location.sensors.values())

    def role_of(self, location_id: str, entity_id: str) -> str | None:
        """Роль датчика в локации.

        Args:
            location_id: Идентификатор локации.
            entity_id: Сущность датчика.

        Returns:
            Роль либо ``None``, если датчик к локации не привязан.
        """
        location = self._locations.get(location_id)
        if location is None:
            return None
        for role, entity in location.sensors.items():
            if entity == entity_id:
                return role
        return None

    def bound_entities(self) -> list[str]:
        """Все сущности, привязанные к локациям.

        Returns:
            Отсортированный список сущностей (датчики комнат и особых зон).
        """
        return sorted(self._roles_by_entity)

    async def prime(self) -> int:
        """Прочитать текущие значения привязанных датчиков (FR-001).

        Без этого снимок на старте пуст: платформа узнаёт о датчике только из
        события изменения, а у датчика, который не менялся (контакт окна), события
        нет вовсе — и «что сейчас в комнате» оставалось бы неизвестным до первого
        изменения. Чтение идёт **мимо журнала**: это не изменение показателя, а
        его текущее значение, и запись его в журнал была бы потоком «каждую
        минуту», который спека запрещает (FR-006).

        Returns:
            Сколько показаний прочитано. Ноль, если читать нечем.
        """
        if self._state_reader is None:
            return 0
        read = 0
        for entity_id in sorted(self._roles_by_entity):
            try:
                value = await self._state_reader(entity_id)
            except Exception as exc:  # noqa: BLE001 — один датчик не мешает другим
                logger.warning(f"Наблюдение за локациями: {entity_id} не прочитан: {exc}")
                continue
            if value is None:
                continue
            self.record(entity_id, value)
            read += 1
        if read:
            logger.info(f"Наблюдение за локациями: прочитано текущих показаний — {read}")
        return read

    def describe(self) -> dict[str, Any]:
        """Описание наблюдения для журнала при старте (FR-012).

        Returns:
            Словарь: сколько локаций и датчиков, какие датчики молчат.
        """
        now = datetime.now(UTC)
        silent: list[str] = []
        for location_id, readings in self._readings.items():
            location = self._locations[location_id]
            for reading in readings.values():
                if (now - reading.at).total_seconds() > location.stale_after_sec:
                    silent.append(reading.entity_id)
        return {
            "locations": len(self._locations),
            "sensors": len(self._roles_by_entity),
            "seen": sum(len(readings) for readings in self._readings.values()),
            "silent": sorted(silent),
        }

    def _unit_of(self, entity_id: str) -> str | None:
        """Единица измерения сущности, если она известна.

        Args:
            entity_id: Сущность Home Assistant.

        Returns:
            Единица измерения либо ``None``.
        """
        if self._unit_provider is None:
            return None
        try:
            return self._unit_provider(entity_id)
        except Exception as exc:  # noqa: BLE001 — единица не важнее показания
            logger.warning(f"Единица измерения {entity_id} не прочитана: {exc}")
            return None
