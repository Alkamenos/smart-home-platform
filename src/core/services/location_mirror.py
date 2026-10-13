"""Зеркало снимков локаций в Home Assistant через MQTT-автообнаружение (спека 016).

Платформа **не умеет создавать сущности** в Home Assistant: она может писать в
уже существующие (``input_text``, ``input_number``). Поэтому зеркало сделано
автообнаружением: платформа публикует в MQTT конфигурацию и значения, а сущности
создаёт сам Home Assistant. Владельцу не нужно заводить десятки помощников.

Публикация идёт через интерфейс адаптера (``mqtt.publish``), а не напрямую:
``core`` не импортирует ``adapters`` (`.ai/04_RULES.md`). Все публикации с
``retain``: после перезапуска Home Assistant сущности восстанавливаются, не
дожидаясь нового события (FR-008, сценарий 2).

Отказ публикации не ломает снимок и журнал (FR-009): неудача считается и
называется в журнале, а состояние продолжает обновляться.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from core.models.location import LocationSnapshot


#: Имя события шины, которое публикует адаптер на каждое изменение состояния.
EVENT_STATE_CHANGE = "state_change"

#: Префикс топиков значений зеркала (параметр дома).
DEFAULT_PREFIX = "behavioral"

#: Префикс автообнаружения Home Assistant.
DISCOVERY_PREFIX = "homeassistant"

#: Роли, у которых значение — «включено/выключено»: в Home Assistant это
#: `binary_sensor`, а не числовой `sensor`.
BINARY_ROLES = frozenset({"motion", "contact", "rain"})

#: Как называется зеркало в Home Assistant как устройство.
MANUFACTURER = "Smart Home Platform"

#: Человекочитаемые имена ролей для Home Assistant: владелец видит их в
#: интерфейсе, и «temperature» там неуместно.
ROLE_LABELS: dict[str, str] = {
    "temperature": "температура",
    "humidity": "влажность",
    "illuminance": "освещённость",
    "pressure": "давление",
    "motion": "движение",
    "contact": "проём",
    "rain": "дождь",
    "wind_speed": "ветер",
    "wind_gust": "порыв ветра",
    "uv_index": "УФ-индекс",
    "co2": "CO₂",
    "soil_moisture": "влага почвы",
    "soil_temperature": "температура почвы",
    "soil_ph": "кислотность почвы",
    "soil_ec": "проводимость почвы",
    "battery": "батарейка",
}


class LocationMirror:
    """Публиковать снимки локаций в Home Assistant.

    Args:
        state: Наблюдение за локациями (источник снимков).
        publish: Как опубликовать топик: ``(topic, payload, retain) -> bool``.
            Обычно адаптер: ``mqtt.publish``.
        prefix: Префикс топиков значений.
        discovery_prefix: Префикс автообнаружения Home Assistant.
        enabled: Публиковать ли вообще (дом без MQTT может выключить зеркало).
    """

    def __init__(
        self,
        *,
        state: Any,
        publish: Callable[[str, str, bool], Awaitable[bool]] | None = None,
        prefix: str = DEFAULT_PREFIX,
        discovery_prefix: str = DISCOVERY_PREFIX,
        enabled: bool = True,
    ) -> None:
        self._state = state
        self._publish = publish
        self._prefix = prefix.strip("/") or DEFAULT_PREFIX
        self._discovery = discovery_prefix.strip("/") or DISCOVERY_PREFIX
        self._enabled = enabled and publish is not None
        #: Что уже объявлено: (локация, роль) и локации целиком. Конфигурация
        #: обнаружения публикуется один раз — повтор не нужен и стоит вызова.
        self._announced: set[tuple[str, str]] = set()
        self._announced_locations: set[str] = set()
        self._published = 0
        self._failed = 0

    def bind(self, event_bus: Any) -> None:
        """Подписаться на изменения состояний и публиковать затронутые локации.

        Args:
            event_bus: Шина событий платформы.

        Returns:
            Ничего.
        """
        if not self._enabled:
            logger.info("Зеркало локаций выключено: публикация в Home Assistant не идёт")
            return
        event_bus.subscribe(EVENT_STATE_CHANGE, self.on_state_change)
        logger.info(f"Зеркало локаций: публикация в Home Assistant ({self.describe()})")

    async def on_state_change(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Опубликовать снимки локаций, которых коснулось изменение.

        Args:
            event_type: Имя события (не используется).
            payload: Полезная нагрузка изменения состояния.
            trace_id: Идентификатор трассы (не используется).

        Returns:
            Ничего.
        """
        del event_type, trace_id
        entity_id = (payload or {}).get("entity_id")
        if not entity_id:
            return
        for location_id in self._state.locations_of(entity_id):
            await self.publish(location_id)

    async def publish_all(self) -> int:
        """Опубликовать все локации — после старта и первичного чтения.

        Returns:
            Сколько локаций опубликовано.
        """
        published = 0
        for location_id in self._state.location_ids():
            if await self.publish(location_id):
                published += 1
        return published

    async def publish(self, location_id: str) -> bool:
        """Опубликовать снимок локации и её объявление в Home Assistant.

        Args:
            location_id: Идентификатор локации.

        Returns:
            True, если снимок опубликован (или зеркало выключено).
        """
        if not self._enabled:
            return False
        snapshot = self._state.snapshot(location_id)
        if snapshot is None:
            return False

        await self._announce(snapshot)
        ok = True
        for role, readings in snapshot.readings.items():
            [reading] = readings[:1]
            ok = (
                await self._send(
                    f"{self._prefix}/location/{location_id}/{role}/state",
                    _state_payload(reading),
                )
                and ok
            )
            ok = (
                await self._send(
                    f"{self._prefix}/location/{location_id}/{role}/attributes",
                    json.dumps(
                        {
                            "value": reading.value,
                            "unit": reading.unit,
                            "at": reading.at,
                            "stale": reading.stale,
                            "available": reading.available,
                            "entity_id": reading.entity_id,
                        },
                        ensure_ascii=False,
                    ),
                )
                and ok
            )

        summary = str(snapshot.derived.get("available_count", 0))
        ok = await self._send(f"{self._prefix}/location/{location_id}/state", summary) and ok
        ok = (
            await self._send(
                f"{self._prefix}/location/{location_id}/attributes",
                snapshot.model_dump_json(),
            )
            and ok
        )
        return ok

    async def _announce(self, snapshot: LocationSnapshot) -> None:
        """Объявить локацию и её показатели в Home Assistant (один раз).

        Args:
            snapshot: Снимок локации.

        Returns:
            Ничего.
        """
        location = snapshot.location
        device = {
            "identifiers": [f"{self._prefix}_{location.id}"],
            "name": location.name,
            "manufacturer": MANUFACTURER,
            "model": location.kind,
        }
        if location.id not in self._announced_locations:
            await self._send(
                f"{self._discovery}/sensor/{self._prefix}_{location.id}/config",
                json.dumps(
                    {
                        "name": "состояние",
                        # `has_entity_name` + `object_id`: без них Home Assistant
                        # собирает идентификатор из имени устройства и имени
                        # сущности — выходило «gostinaia_gostinaia_temperature».
                        "has_entity_name": True,
                        "object_id": f"{self._prefix}_{location.id}",
                        "unique_id": f"{self._prefix}_{location.id}",
                        "state_topic": f"{self._prefix}/location/{location.id}/state",
                        "json_attributes_topic": (
                            f"{self._prefix}/location/{location.id}/attributes"
                        ),
                        "unit_of_measurement": "шт.",
                        "icon": "mdi:home-analytics",
                        "device": device,
                    },
                    ensure_ascii=False,
                ),
            )
            self._announced_locations.add(location.id)

        for role in snapshot.readings:
            key = (location.id, role)
            if key in self._announced:
                continue
            component = "binary_sensor" if role in BINARY_ROLES else "sensor"
            config: dict[str, Any] = {
                "name": ROLE_LABELS.get(role, role),
                "has_entity_name": True,
                "object_id": f"{self._prefix}_{location.id}_{role}",
                "unique_id": f"{self._prefix}_{location.id}_{role}",
                "state_topic": f"{self._prefix}/location/{location.id}/{role}/state",
                "json_attributes_topic": (
                    f"{self._prefix}/location/{location.id}/{role}/attributes"
                ),
                "device": device,
            }
            if role in BINARY_ROLES:
                config["payload_on"] = "on"
                config["payload_off"] = "off"
            else:
                unit = _unit_of(snapshot, role)
                if unit:
                    config["unit_of_measurement"] = unit
            await self._send(
                f"{self._discovery}/{component}/{self._prefix}_{location.id}_{role}/config",
                json.dumps(config, ensure_ascii=False),
            )
            self._announced.add(key)

    async def _send(self, topic: str, payload: str) -> bool:
        """Опубликовать топик, не роняя автоматику при отказе (FR-009).

        Args:
            topic: Топик MQTT.
            payload: Полезная нагрузка.

        Returns:
            True, если опубликовано.
        """
        assert self._publish is not None  # проверено в __init__
        try:
            ok = await self._publish(topic, payload, True)
        except Exception as exc:  # noqa: BLE001 — отказ зеркала не ломает снимок
            self._failed += 1
            logger.warning(f"Зеркало локаций: публикация {topic} не удалась: {exc}")
            return False
        if ok:
            self._published += 1
        else:
            self._failed += 1
            logger.warning(f"Зеркало локаций: публикация {topic} отвергнута Home Assistant")
        return bool(ok)

    def describe(self) -> dict[str, Any]:
        """Описание зеркала для журнала и готовности.

        Returns:
            Словарь: включено ли, префикс, сколько опубликовано и сколько отказов.
        """
        return {
            "enabled": self._enabled,
            "prefix": self._prefix,
            "published": self._published,
            "failed": self._failed,
        }


def _state_payload(reading: Any) -> str:
    """Значение показания для топика состояния.

    Args:
        reading: Показание снимка.

    Returns:
        Строка значения (число без лишних нулей, иначе как есть).
    """
    value = reading.value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _unit_of(snapshot: LocationSnapshot, role: str) -> str | None:
    """Единица измерения роли по снимку.

    Args:
        snapshot: Снимок локации.
        role: Роль датчика.

    Returns:
        Единица либо ``None``.
    """
    readings = snapshot.readings.get(role) or []
    return readings[0].unit if readings else None
