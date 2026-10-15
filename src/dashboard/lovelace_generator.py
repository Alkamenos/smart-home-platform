"""Генератор дашборда Home Assistant из дома (BACKLOG B79).

Дашборд собирается из манифеста: комнаты, локации, их датчики и приборы. Здесь
ничего не выдумывается — в карточках только те сущности, которые есть в доме, и
только те типы карточек, которые Home Assistant знает.

Прежний генератор этого не делал, и владелец увидел «ошибка конфигурации» почти в
каждой второй карточке (жалоба 2026-10-16):

* карточки автоматов ссылались на придуманные сущности вида
  ``binary_sensor.<русское имя>_active`` — их не существует по определению;
* использовался тип ``entity-button``, которого в современном Home Assistant нет;
* обогреватель-выключатель клался в карточку ``thermostat``, а она требует
  ``climate.*``.

Отсюда правило генератора: **сначала дом, потом карточка**. Не «сделаем красивую
карточку автомата», а «покажем то, что в доме действительно есть».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from core.models.manifest import (
    Manifest,
    iter_role_entities,
)


#: Подпись и значок роли датчика.
#:
#: Роль — слово из манифеста (`temperature`, `soil_moisture`), и показывать её
#: владельцу как есть нельзя. Незнакомая роль не выдумывается: она называется
#: собой, но по-человечески — с пробелами вместо подчёркиваний.
SENSOR_LABELS: dict[str, tuple[str, str]] = {
    "temperature": ("Температура", "mdi:thermometer"),
    "humidity": ("Влажность", "mdi:water-percent"),
    "motion": ("Движение", "mdi:motion-sensor"),
    "occupancy": ("Присутствие", "mdi:motion-sensor"),
    "person": ("Присутствие", "mdi:account"),
    "illuminance": ("Освещённость", "mdi:brightness-5"),
    "lux": ("Освещённость", "mdi:brightness-5"),
    "battery": ("Батарейка", "mdi:battery"),
    "contact": ("Открытие", "mdi:door"),
    "rain": ("Дождь", "mdi:weather-rainy"),
    "pressure": ("Давление", "mdi:gauge"),
    "wind_speed": ("Ветер", "mdi:weather-windy"),
    "wind_gust": ("Порывы ветра", "mdi:weather-windy-variant"),
    "uv_index": ("УФ-индекс", "mdi:sun-wireless"),
    "co2": ("Углекислый газ", "mdi:molecule-co2"),
    "soil_moisture": ("Влажность почвы", "mdi:water-percent"),
    "soil_temperature": ("Температура почвы", "mdi:thermometer"),
    "soil_ec": ("Плодородие почвы", "mdi:sprout"),
    "animal": ("Животное", "mdi:paw"),
    "vehicle": ("Машина", "mdi:car"),
}

#: Значок прибора по его типу.
DEVICE_ICONS: dict[str, str] = {
    "light": "mdi:lightbulb",
    "light_motion": "mdi:lightbulb",
    "climate": "mdi:radiator",
    "climate_hysteresis": "mdi:radiator",
    "ventilation": "mdi:fan",
    "ventilation_humidity": "mdi:fan",
    "fan": "mdi:fan",
    "cover": "mdi:window-shutter",
}


class LovelaceGenerator:
    """Генератор конфигурации дашборда Home Assistant."""

    def generate(self, manifest: Manifest) -> dict[str, Any]:
        """Собрать дашборд из дома.

        Комнаты и локации — **разные разделы манифеста**, и в дашборде они идут
        отдельными представлениями: путать их нельзя (требование владельца
        2026-10-15).

        Args:
            manifest: Манифест дома.

        Returns:
            Конфигурация Lovelace: название и представления.
        """
        views = [self._place_view(room) for room in manifest.rooms]
        views += [self._place_view(location) for location in manifest.locations]
        title = str(getattr(manifest.dashboard, "title", "") or "").strip()
        return {"title": title, "views": views}

    def _place_view(self, place: Any) -> dict[str, Any]:
        """Собрать представление одного места: комнаты или локации.

        Args:
            place: Комната либо локация манифеста.

        Returns:
            Представление Lovelace.
        """
        cards: list[dict[str, Any]] = []
        sensors = self._sensor_card(place)
        if sensors is not None:
            cards.append(sensors)
        devices = self._device_card(place)
        if devices is not None:
            cards.append(devices)
        if not cards:
            cards.append(
                {
                    "type": "markdown",
                    "content": f"В месте «{place.name}» пока нечего показать: "
                    "ни датчиков, ни приборов.",
                }
            )
        return {"title": place.name, "path": self._path(place.id), "cards": cards}

    def _sensor_card(self, place: Any) -> dict[str, Any] | None:
        """Собрать карточку датчиков места.

        Args:
            place: Комната либо локация манифеста.

        Returns:
            Карточка `entities` либо ``None``, если датчиков нет.
        """
        entities: list[dict[str, Any]] = []
        for role, entity in iter_role_entities(place.sensors):
            label, icon = SENSOR_LABELS.get(
                role, (role.replace("_", " ").capitalize(), "mdi:help-circle")
            )
            entities.append({"entity": entity, "name": label, "icon": icon})
        if not entities:
            return None
        return {"type": "entities", "title": "Датчики", "entities": entities}

    def _device_card(self, place: Any) -> dict[str, Any] | None:
        """Собрать карточку приборов места.

        Прибор описан в манифесте своим идентификатором Home Assistant, поэтому
        карточка ссылается на существующую сущность, а не на придуманное имя.

        Args:
            place: Комната либо локация манифеста.

        Returns:
            Карточка `entities` либо ``None``, если приборов нет.
        """
        entities: list[dict[str, Any]] = []
        for device in getattr(place, "devices", []) or []:
            if "." not in str(device.id):
                # Идентификатор без домена — не сущность дома: показать её нельзя.
                continue
            entities.append(
                {
                    "entity": device.id,
                    "name": device.name or device.id,
                    "icon": DEVICE_ICONS.get(str(device.type), "mdi:help-circle"),
                }
            )
        if not entities:
            return None
        return {"type": "entities", "title": "Управление", "entities": entities}

    def _path(self, place_id: str) -> str:
        """Путь представления по идентификатору места.

        Home Assistant принимает в пути только латиницу, цифры и дефис: имя
        места в пути недопустимо.

        Args:
            place_id: Идентификатор места.

        Returns:
            Путь представления.
        """
        cleaned = "".join(
            char if char.isalnum() and char.isascii() else "-" for char in place_id.lower()
        )
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        return cleaned.strip("-") or "place"
