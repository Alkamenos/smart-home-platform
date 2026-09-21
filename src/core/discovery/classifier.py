"""Device classifier - определяет категорию и назначает шаблоны."""

from __future__ import annotations

import re

from .models import BehaviorTemplate, DeviceCategory


class DeviceClassifier:
    """Классифицирует устройства и автоматически назначает шаблоны."""

    # Автоприменение шаблонов по категориям
    AUTO_TEMPLATES: dict[DeviceCategory, str] = {
        DeviceCategory.LIGHTING: BehaviorTemplate.LIGHTING.value,
        DeviceCategory.CLIMATE_CONTROL: BehaviorTemplate.CLIMATE_CONTROL.value,
        DeviceCategory.VENTILATION: BehaviorTemplate.HUMIDITY_VENTILATION.value,
    }

    # Паттерны для категорий
    CATEGORY_PATTERNS: list[tuple[str, DeviceCategory]] = [
        (r"temperat|temp|температур", DeviceCategory.TEMPERATURE_SENSOR),
        (r"humid|влажн", DeviceCategory.HUMIDITY_SENSOR),
        (r"motion|occupancy|движ|presence", DeviceCategory.MOTION_SENSOR),
        (r"mold|plesen|плесень", DeviceCategory.MONITORING_ONLY),
        (r"water|leak|depth|uroven|уровен", DeviceCategory.MONITORING_ONLY),
        (r"lux|illuminance|освещ", DeviceCategory.MONITORING_ONLY),
    ]

    # Маппинг доменов на категории
    DOMAIN_MAP: dict[str, DeviceCategory] = {
        "light": DeviceCategory.LIGHTING,
        "switch": DeviceCategory.SWITCH_CONTROL,
        "fan": DeviceCategory.VENTILATION,
        "climate": DeviceCategory.CLIMATE_CONTROL,
        "cover": DeviceCategory.COVER_CONTROL,
        "binary_sensor": DeviceCategory.MOTION_SENSOR,
        "sensor": DeviceCategory.MONITORING_ONLY,
    }

    @classmethod
    def classify(
        cls, entity_id: str, domain: str, attributes: dict
    ) -> tuple[DeviceCategory, str | None, bool]:
        """
        Определить категорию, шаблон и флаг автоприменения.

        Returns:
            (category, suggested_template, auto_apply)
        """
        entity_lower = entity_id.lower()

        # 1. Специфичные паттерны
        for pattern, category in cls.CATEGORY_PATTERNS:
            if re.search(pattern, entity_lower, re.IGNORECASE):
                template = cls.AUTO_TEMPLATES.get(category)
                auto_apply = template is not None
                return category, template, auto_apply

        # 2. По домену
        category = cls.DOMAIN_MAP.get(domain, DeviceCategory.MONITORING_ONLY)
        template = cls.AUTO_TEMPLATES.get(category)
        auto_apply = template is not None

        return category, template, auto_apply

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
