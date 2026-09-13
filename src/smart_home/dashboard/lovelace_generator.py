"""Генератор дашбордов для Home Assistant Lovelace."""

from __future__ import annotations

from smart_home.core.models.manifest import Manifest, Zone, AnyDevice, BehaviorConfig


class LovelaceGenerator:
    """Генератор YAML-конфигурации для Home Assistant Lovelace."""

    def generate(self, manifest: Manifest) -> dict:
        """
        Сгенерировать конфигурацию дашборда Lovelace из манифеста.

        Args:
            manifest: Объект Manifest с зонами, устройствами и поведениями.

        Returns:
            dict: Словарь с конфигурацией Lovelace Dashboard.
        """
        dashboard = {
            "title": manifest.dashboard.title,
            "views": self._generate_views(manifest.zones, manifest.devices),
        }
        return dashboard

    def _generate_views(self, zones: list[Zone], devices: list[AnyDevice]) -> list[dict]:
        """
        Создать вкладки дашборда по зонам (комнатам).

        Args:
            zones: Список зон из манифеста.
            devices: Список устройств из манифеста.

        Returns:
            list[dict]: Список вкладок Lovelace.
        """
        views = []
        for zone in zones:
            zone_devices = [d for d in devices if d.room == zone.id]
            view = self._create_zone_view(zone, zone_devices)
            views.append(view)
        return views

    def _create_zone_view(self, zone: Zone, devices: list[AnyDevice]) -> dict:
        """
        Создать вкладку для одной зоны.

        Args:
            zone: Объект зоны.
            devices: Список устройств в этой зоне.

        Returns:
            dict: Конфигурация вкладки Lovelace.
        """
        cards = []
        for device in devices:
            device_cards = self._create_device_cards(device)
            cards.extend(device_cards)

        # Если нет устройств, добавим пустую карточку
        if not cards:
            cards.append({
                "type": "markdown",
                "content": f"В зоне '{zone.name}' нет устройств."
            })

        return {
            "title": zone.name,
            "path": zone.id,
            "cards": cards,
        }

    def _create_device_cards(self, device: AnyDevice) -> list[dict]:
        """
        Создать карточки для устройства с кнопками управления и индикаторами поведения.

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

    def _get_entity_id(self, device: AnyDevice) -> str:
        """
        Получить entity_id для устройства на основе его типа.

        Args:
            device: Устройство из манифеста.

        Returns:
            str: Entity ID в формате Home Assistant.
        """
        type_mapping = {
            "light_motion": "light",
            "climate_hysteresis": "climate",
            "ventilation_humidity": "fan",
        }
        ha_type = type_mapping.get(device.type, "switch")
        name_slug = device.name.lower().replace(" ", "_").replace("-", "_")
        return f"{ha_type}.{name_slug}"

    def _create_control_card(self, device: AnyDevice, entity_id: str) -> dict:
        """
        Создать карточку с кнопками управления устройством.

        Args:
            device: Устройство из манифеста.
            entity_id: Entity ID устройства в Home Assistant.

        Returns:
            dict: Конфигурация карточки управления.
        """
        # Определяем тип карточки в зависимости от типа устройства
        if device.type == "light_motion":
            return {
                "type": "entities",
                "title": device.name,
                "entities": [
                    {
                        "entity": entity_id,
                        "name": device.name,
                    }
                ],
                "show_header_toggle": True,
            }
        elif device.type == "climate_hysteresis":
            return {
                "type": "thermostat",
                "entity": entity_id,
                "name": device.name,
            }
        elif device.type == "ventilation_humidity":
            return {
                "type": "entities",
                "title": device.name,
                "entities": [
                    {
                        "entity": entity_id,
                        "name": device.name,
                    }
                ],
                "show_header_toggle": True,
            }
        else:
            return {
                "type": "entities",
                "title": device.name,
                "entities": [
                    {
                        "entity": entity_id,
                        "name": device.name,
                    }
                ],
            }

    def _create_behavior_indicator(self, device: AnyDevice, behavior: BehaviorConfig) -> dict:
        """
        Создать карточку-индикатор активности поведения.

        Args:
            device: Устройство, к которому относится поведение.
            behavior: Конфигурация поведения.

        Returns:
            dict: Конфигурация карточки-индикатора.
        """
        # Создаем имя для сенсора активности поведения
        behavior_name = behavior.template.replace(".yaml", "").replace(".yml", "")
        sensor_name = f"{device.name} - {behavior_name}"
        sensor_slug = f"{device.name.lower().replace(' ', '_').replace('-', '_')}_{behavior_name}"
        sensor_entity_id = f"binary_sensor.{sensor_slug}_active"

        return {
            "type": "entity-button",
            "entity": sensor_entity_id,
            "name": f"{behavior_name} (приоритет {behavior.priority})",
            "icon": "mdi:automation",
            "tap_action": {
                "action": "more-info"
            },
            "hold_action": {
                "action": "none"
            },
        }
