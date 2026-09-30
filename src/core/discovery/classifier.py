"""Device classifier - определяет категорию и назначает шаблоны."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re

from .models import BehaviorTemplate, DeviceCategory


__all__ = ["DeviceClassifier"]


class DeviceClassifier:
    """Классифицирует устройства и автоматически назначает шаблоны."""

    # Автоприменение шаблонов по категориям
    AUTO_TEMPLATES: dict[DeviceCategory, str] = {
        DeviceCategory.LIGHTING: BehaviorTemplate.LIGHTING.value,
        DeviceCategory.CLIMATE_CONTROL: BehaviorTemplate.CLIMATE_CONTROL.value,
        DeviceCategory.VENTILATION: BehaviorTemplate.HUMIDITY_VENTILATION.value,
        DeviceCategory.COVER_CONTROL: BehaviorTemplate.GENERIC_COVER.value,
        DeviceCategory.SWITCH_CONTROL: BehaviorTemplate.GENERIC_SWITCH.value,
    }

    # Паттерны для категорий (порядок важен!)
    # Специфичные паттерны должны быть ПЕРЕД общими
    CATEGORY_PATTERNS: list[tuple[str, DeviceCategory]] = [
        # Temperature sensors (специфично)
        (
            r"\b(temperature|temperatura|temp(?:erature)?|температур)\b",
            DeviceCategory.TEMPERATURE_SENSOR,
        ),
        # Humidity sensors (специфично)
        (r"\b(humidity|humid|влажн)\b", DeviceCategory.HUMIDITY_SENSOR),
        # Motion sensors (специфично)
        (
            r"\b(motion|movement|occupancy|presence|движ|присут|детектор_движ)\b",
            DeviceCategory.MOTION_SENSOR,
        ),
        # Water/Leak sensors (специфично - до door)
        (r"\b(water|leak|flooding|влага|протечка|затопл)\b", DeviceCategory.MONITORING_ONLY),
        # Air quality & pollution (специфично)
        (
            r"\b(pm2\.5|pm10|co2|tvoc|nox|so2|no2|air_quality|воздух)\b",
            DeviceCategory.MONITORING_ONLY,
        ),
        # Vibration/Shock sensors (специфично)
        (r"\b(vibration|shake|seismic|вибрац)\b", DeviceCategory.MONITORING_ONLY),
        # Gas sensors (специфично - перед smoke)
        (r"\b(gas|дым|газ|угарн)\b|smoke", DeviceCategory.MONITORING_ONLY),
        # Light sensors (специфично - люкс, освещенность)
        (r"\b(lux|illuminance|light_level|освещ|люкс)\b", DeviceCategory.MONITORING_ONLY),
        # Power/Energy sensors (специфично)
        (
            r"\b(power|energy|voltage|current|amperage|frequency|мощн|энерг|напряж|ток)\b",
            DeviceCategory.MONITORING_ONLY,
        ),
        # Battery sensors (специфично)
        (r"\b(battery|аккум|батарея)\b", DeviceCategory.MONITORING_ONLY),
        # Mold/Moisture risk (специфично)
        (r"\b(mold|plesen|плесень)\b", DeviceCategory.MONITORING_ONLY),
        # Door/Window/Contact sensors (ОБЩЕЕ - после специфичных)
        (r"\b(door|window|contact|дверь|окно|контакт)\b", DeviceCategory.MONITORING_ONLY),
        # Depth/Level sensors (специфично)
        (r"\b(depth|level|height|уровен|глубин)\b", DeviceCategory.MONITORING_ONLY),
    ]

    # Маппинг доменов на категории
    DOMAIN_MAP: dict[str, DeviceCategory] = {
        "light": DeviceCategory.LIGHTING,
        "switch": DeviceCategory.SWITCH_CONTROL,
        "fan": DeviceCategory.VENTILATION,
        "climate": DeviceCategory.CLIMATE_CONTROL,
        "cover": DeviceCategory.COVER_CONTROL,
        "lock": DeviceCategory.MONITORING_ONLY,  # Requires manual setup for security
        "binary_sensor": DeviceCategory.MOTION_SENSOR,
        "sensor": DeviceCategory.MONITORING_ONLY,
    }

    @staticmethod
    def _searchable_text(entity_id: str, friendly_name: str) -> str:
        """Собирает текст для поиска по паттернам.

        Разделители entity_id/friendly_name (точки, дефисы, подчёркивания)
        заменяются пробелами: символ ``_`` является «словным» символом regex,
        из-за чего ``\\b`` не срабатывал в идентификаторах вида
        ``sensor.temperatura_v_teplitse`` (Known Issue #4).

        Args:
            entity_id: Идентификатор сущности.
            friendly_name: Человекочитаемое имя устройства.

        Returns:
            Нормализованный текст для поиска по паттернам.
        """
        return re.sub(r"[._\-]+", " ", f"{entity_id} {friendly_name}".lower())

    @classmethod
    def classify(
        cls, entity_id: str, domain: str, attributes: dict
    ) -> tuple[DeviceCategory, str | None, bool]:
        """
        Определить категорию, шаблон и флаг автоприменения.

        Returns:
            (category, suggested_template, auto_apply)
        """
        device_class = attributes.get("device_class", "").lower()

        # 1. Проверяем device_class (самый надежный источник)
        if device_class:
            category, template, auto_apply = cls._classify_by_device_class(device_class, domain)
            if category != DeviceCategory.MONITORING_ONLY:
                return category, template, auto_apply

        # 2. Проверяем специфичные паттерны в entity_id и friendly_name
        full_text = cls._searchable_text(entity_id, attributes.get("friendly_name", ""))

        for pattern, pattern_category in cls.CATEGORY_PATTERNS:
            if re.search(pattern, full_text, re.IGNORECASE):
                template = cls.AUTO_TEMPLATES.get(pattern_category)
                auto_apply = template is not None
                return pattern_category, template, auto_apply

        # 3. Специальная обработка для switch (may be lighting or automation)
        if domain == "switch":
            category, template, auto_apply = cls._classify_switch(entity_id, attributes)
            if category != DeviceCategory.MONITORING_ONLY:
                return category, template, auto_apply

        # 4. Специальная обработка для fan (может быть вентилляцией или охлаждением)
        if domain == "fan":
            category, template, auto_apply = cls._classify_fan(entity_id, attributes)
            if category != DeviceCategory.MONITORING_ONLY:
                return category, template, auto_apply

        # 5. По умолчанию по домену
        category = cls.DOMAIN_MAP.get(domain, DeviceCategory.MONITORING_ONLY)
        template = cls.AUTO_TEMPLATES.get(category)
        auto_apply = template is not None

        return category, template, auto_apply

    @classmethod
    def _classify_by_device_class(
        cls, device_class: str, domain: str
    ) -> tuple[DeviceCategory, str | None, bool]:
        """Классифицировать по device_class (HA standard)."""
        if not device_class:
            # Fallback to domain-based classification
            category = cls.DOMAIN_MAP.get(domain, DeviceCategory.MONITORING_ONLY)
            template = cls.AUTO_TEMPLATES.get(category)
            auto_apply = template is not None
            return category, template, auto_apply

        # Lighting
        if device_class in ("light", "dimmer"):
            return (
                DeviceCategory.LIGHTING,
                BehaviorTemplate.LIGHTING.value,
                True,
            )

        # Climate
        if device_class in ("temperature", "thermostat", "hvac"):
            return (
                DeviceCategory.CLIMATE_CONTROL,
                BehaviorTemplate.CLIMATE_CONTROL.value,
                True,
            )

        # Ventilation/Fan
        if device_class in ("fan", "ventilation"):
            return (
                DeviceCategory.VENTILATION,
                BehaviorTemplate.HUMIDITY_VENTILATION.value,
                True,
            )

        # Cover (blinds, garage door, etc)
        if device_class in ("blind", "shutter", "door", "garage", "gate", "window", "awning"):
            return (
                DeviceCategory.COVER_CONTROL,
                BehaviorTemplate.GENERIC_COVER.value,
                True,
            )

        # Lock
        if device_class in ("lock", "door_lock"):
            return (
                DeviceCategory.SECURITY,
                BehaviorTemplate.SMART_LOCK.value,
                False,  # Don't auto-apply locks for safety
            )

        # Sensors
        if device_class == "temperature":
            return DeviceCategory.TEMPERATURE_SENSOR, None, False
        if device_class == "humidity":
            return DeviceCategory.HUMIDITY_SENSOR, None, False
        if device_class == "motion":
            return DeviceCategory.MOTION_SENSOR, None, False

        # Default: fallback to domain mapping
        category = cls.DOMAIN_MAP.get(domain, DeviceCategory.MONITORING_ONLY)
        template = cls.AUTO_TEMPLATES.get(category)
        auto_apply = template is not None
        return category, template, auto_apply

    @classmethod
    def _classify_switch(
        cls, entity_id: str, attributes: dict
    ) -> tuple[DeviceCategory, str | None, bool]:
        """Классифицировать switch как lighting или automation."""
        entity_lower = entity_id.lower()
        friendly_name = attributes.get("friendly_name", "").lower()
        full_text = cls._searchable_text(entity_lower, friendly_name)

        # Lighting indicators
        if re.search(r"light|lamp|освещ|лампа|яркост", full_text, re.IGNORECASE):
            return (
                DeviceCategory.LIGHTING,
                BehaviorTemplate.LIGHTING.value,
                True,
            )

        # Automation/Control (generic switch)
        return DeviceCategory.SWITCH_CONTROL, None, False

    @classmethod
    def _classify_fan(
        cls, entity_id: str, attributes: dict
    ) -> tuple[DeviceCategory, str | None, bool]:
        """Классифицировать fan как ventilation или cooling."""
        entity_lower = entity_id.lower()
        friendly_name = attributes.get("friendly_name", "").lower()
        full_text = cls._searchable_text(entity_lower, friendly_name)

        # Ventilation (humidity-controlled)
        # "vent" добавлен к "ventilat": реальные entity_id вроде fan.bathroom_vent
        # не содержат полного "ventilation" (Known Issue #4)
        if re.search(r"\bvent\b|ventilat|exhaust|hood|вентил|вытяжк", full_text, re.IGNORECASE):
            return (
                DeviceCategory.VENTILATION,
                BehaviorTemplate.HUMIDITY_VENTILATION.value,
                True,
            )

        # Cooling/Circulation fan (speed-controlled)
        if re.search(r"cooling|cool|air|circulation|охлад|воздух", full_text, re.IGNORECASE):
            return DeviceCategory.VENTILATION, None, False

        # Generic fan (no auto-apply)
        return DeviceCategory.VENTILATION, None, False

    @classmethod
    def extract_room_name(cls, entity_id: str) -> str | None:
        """Извлечь название комнаты из entity_id."""
        parts = entity_id.split(".")
        if len(parts) < 2:
            return None

        name_part = parts[1]
        name_part = re.sub(
            r"_(temperature|humidity|motion|sensor|light|switch|lux|depth|level|main|vent|ac)$",
            "",
            name_part,
            flags=re.IGNORECASE,
        )
        name_part = re.sub(r"_?\d+$", "", name_part)
        return name_part if name_part else None

    @classmethod
    def get_auto_apply_count(cls, devices: list) -> dict[str, int]:
        """Подсчитать сколько устройств можно применить автоматически."""
        counts = {"auto_apply": 0, "manual": 0}
        for d in devices:
            if getattr(d, "auto_apply", False):
                counts["auto_apply"] += 1
            else:
                counts["manual"] += 1
        return counts
