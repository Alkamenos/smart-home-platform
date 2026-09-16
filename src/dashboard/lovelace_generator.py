"""Генератор дашбордов для Home Assistant Lovelace."""

from __future__ import annotations

from core.models.manifest import (
    BehaviorConfig,
    DeviceConfig,
    Manifest,
    RoomConfig,
)


class LovelaceGenerator:
    """Генератор YAML-конфигурации для Home Assistant Lovelace."""

    def generate(self, manifest: Manifest) -> dict:
        """
        Сгенерировать конфигурацию дашборда Lovelace из манифеста.

        Args:
            manifest: Объект Manifest с комнатами и устройствами.

        Returns:
            dict: Словарь с конфигурацией Lovelace Dashboard.
        """
        dashboard = {
            "title": manifest.dashboard.title,
            "views": self._generate_views(manifest.rooms),
        }
        return dashboard

    def _generate_views(self, rooms: list[RoomConfig]) -> list[dict]:
        """
        Создать вкладки дашборда по комнатам.

        Args:
            rooms: Список комнат из манифеста.

        Returns:
            list[dict]: Список вкладок Lovelace.
        """
        views = []
        for room in rooms:
            view = self._create_room_view(room)
            views.append(view)
        return views

    def _create_room_view(self, room: RoomConfig) -> dict:
        """
        Создать вкладку для одной комнаты.

        Args:
            room: Объект комнаты.

        Returns:
            dict: Конфигурация вкладки Lovelace.
        """
        cards = []

        # Карточки сенсоров комнаты
        if room.sensors:
            sensor_cards = self._create_sensor_cards(room)
            cards.extend(sensor_cards)

        # Карточки устройств
        for device in room.devices:
            device_cards = self._create_device_cards(device)
            cards.extend(device_cards)

        # Если нет устройств, добавим пустую карточку
        if not cards:
            cards.append(
                {
                    "type": "markdown",
                    "content": f"В комнате '{room.name}' нет устройств.",
                }
            )

        return {
            "title": room.name,
            "path": room.id,
            "cards": cards,
        }

    def _create_sensor_cards(self, room: RoomConfig) -> list[dict]:
        """
        Создать карточки для сенсоров комнаты.

        Args:
            room: Комната с сенсорами.

        Returns:
            list[dict]: Список карточек сенсоров.
        """
        cards = []
        sensor_type_config = {
            "motion": {"icon": "mdi:motion-sensor", "name": "Движение"},
            "temperature": {"icon": "mdi:thermometer", "name": "Температура"},
            "humidity": {"icon": "mdi:water-percent", "name": "Влажность"},
            "lux": {"icon": "mdi:brightness-5", "name": "Освещённость"},
            "contact": {"icon": "mdi:door", "name": "Контакт"},
        }

        for sensor_type, entity_id in room.sensors.items():
            config = sensor_type_config.get(sensor_type, {})
            cards.append(
                {
                    "type": "entity",
                    "entity": entity_id,
                    "name": config.get("name", sensor_type),
                    "icon": config.get("icon", "mdi:help-circle"),
                }
            )

        return cards

    def _create_device_cards(self, device: DeviceConfig) -> list[dict]:
        """
        Создать карточки для устройства.

        Args:
            device: Устройство из манифеста.

        Returns:
            list[dict]: Список карточек Lovelace для устройства.
        """
        cards = []

        # Основная карточка устройства
        entity_id = self._get_entity_id(device)
        control_card = self._create_control_card(device, entity_id)
        cards.append(control_card)

        # Карточки с индикаторами активности для каждого behavior
        for behavior in device.behaviors:
            indicator_card = self._create_behavior_indicator(device, behavior)
            cards.append(indicator_card)

        return cards

    def _get_entity_id(self, device: DeviceConfig) -> str:
        """
        Получить entity_id для устройства.

        Если device.id уже содержит точку (например, light.kitchen),
        используем его как есть. Иначе генерируем из типа и имени.

        Args:
            device: Устройство из манифеста.

        Returns:
            str: Entity ID в формате Home Assistant.
        """
        if "." in device.id:
            return device.id

        type_mapping = {
            "light": "light",
            "light_motion": "light",
            "climate": "climate",
            "climate_hysteresis": "climate",
            "ventilation": "fan",
            "ventilation_humidity": "fan",
        }
        ha_type = type_mapping.get(device.type, "switch")
        name_slug = device.id.lower().replace(" ", "_").replace("-", "_")
        return f"{ha_type}.{name_slug}"

    def _create_control_card(self, device: DeviceConfig, entity_id: str) -> dict:
        """
        Создать карточку управления устройством.

        Args:
            device: Устройство из манифеста.
            entity_id: Entity ID устройства в Home Assistant.

        Returns:
            dict: Конфигурация карточки управления.
        """
        display_name = device.name or device.id

        if device.type in ("light", "light_motion"):
            return {
                "type": "entities",
                "title": display_name,
                "entities": [{"entity": entity_id, "name": display_name}],
                "show_header_toggle": True,
            }
        elif device.type in ("climate", "climate_hysteresis"):
            return {
                "type": "thermostat",
                "entity": entity_id,
                "name": display_name,
            }
        elif device.type in ("ventilation", "ventilation_humidity"):
            return {
                "type": "entities",
                "title": display_name,
                "entities": [{"entity": entity_id, "name": display_name}],
                "show_header_toggle": True,
            }
        else:
            return {
                "type": "entities",
                "title": display_name,
                "entities": [{"entity": entity_id, "name": display_name}],
            }

    def _create_behavior_indicator(self, device: DeviceConfig, behavior: BehaviorConfig) -> dict:
        """
        Создать карточку-индикатор активности поведения.

        Args:
            device: Устройство, к которому относится поведение.
            behavior: Конфигурация поведения.

        Returns:
            dict: Конфигурация карточки-индикатора.
        """
        display_name = device.name or device.id
        behavior_name = behavior.template.replace(".yaml", "").replace(".yml", "")
        sensor_slug = f"{display_name.lower().replace(' ', '_')}_{behavior_name}"
        sensor_entity_id = f"binary_sensor.{sensor_slug}_active"

        return {
            "type": "entity-button",
            "entity": sensor_entity_id,
            "name": f"{behavior_name} (приоритет {behavior.priority})",
            "icon": "mdi:automation",
            "tap_action": {"action": "more-info"},
            "hold_action": {"action": "none"},
        }
