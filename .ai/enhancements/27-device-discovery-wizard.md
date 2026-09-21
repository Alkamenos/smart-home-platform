
Ты — senior Python/Full-stack разработчик, работающий над проектом **Smart Home Platform V3**. Платформа управляет умным домом через FSM (конечные автоматы) и интегрируется с Home Assistant через WebSocket.

### 📌 Ключевая проблема

Платформа успешно подключена к HA через WebSocket и получает события, но не знает что с ними делать:

```
WARNING | core.fsm.engine:trigger:407 - No FSM definition found for entity sensor.temperatura_v_teplitse_ogurtsy_humidity
```

**Причина:** `ManifestAutomationGenerator` генерирует FSM только для устройств из `manifest.yaml`. 200+ устройств пользователя не описаны.

### ✅ Что уже работает

- **HAAdapter** (`src/adapters/ha_adapter.py`) — WebSocket, метод `_ws_client.get_states()` уже существует
- **ManifestAutomationGenerator** — генерирует FSM из манифеста
- **FSMEngine** — `register_definition()` уже есть
- **EventRouter** — `add_mapping()` уже есть
- **Шаблоны:** `lighting`, `night_light`, `climate_control`, `humidity_ventilation` — уже работают
- **WebUI FastAPI** — dark theme Bootstrap 5
- **Container** — DI контейнер

### 📁 Структура проекта

```
src/
├── adapters/ha_adapter.py          # get_states() уже есть
├── core/
│   ├── manifest_generator.py       # Генерирует FSM
│   ├── container.py                # DI контейнер
│   ├── fsm/engine.py               # register_definition()
│   ├── events/event_router.py      # add_mapping()
│   └── models/manifest.py
└── webui/
    ├── app.py
    ├── routes.py
    └── templates/
```

### 📄 Структура манифеста

```yaml
rooms:
  - id: kitchen
    name: Kitchen
    sensors:
      motion: binary_sensor.kitchen_motion
      temperature: sensor.kitchen_temperature
    devices:
      - id: light.kitchen
        type: light
        behaviors:
          - template: lighting
            priority: 10
            params:
              brightness: 255
              motion_timeout_sec: 180
```

---

## 🎯 ЗАДАЧА

Реализовать **Device Discovery Wizard** который:

1. **Сканирует** все 200+ устройств из HA через `get_states()`
2. **Классифицирует** устройства по типам и комнатам
3. **Автоматически применяет** шаблоны (свет→lighting, климат→climate_control, вентиляция→humidity_ventilation)
4. **Обновляет манифест** с **hot reload** FSM

### Требования для 200+ устройств:
- ⚡ Пагинация (по 20-30 устройств на страницу)
- 📊 Прогресс-бар сканирования
- 🔍 Фильтры: по домену, по комнате, по категории
- ⚡ Быстрое применение (не нужно подтверждать каждое устройство)
- 🏠 Группировка по HA Areas (если настроены)

---

## 📁 ФАЙЛЫ ДЛЯ СОЗДАНИЯ

```
src/core/discovery/
├── __init__.py
├── models.py              # Pydantic модели
├── classifier.py          # Классификация + шаблоны
└── discovery_service.py   # Сканирование с пагинацией

src/webui/
├── routes_discovery.py    # API endpoints
└── templates/
    └── discovery.html     # Wizard с пагинацией

tests/
└── test_discovery_classifier.py
```

---

## 🔧 ШАГ 1: Модели (`src/core/discovery/models.py`)

```python
"""Pydantic models for device discovery."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DeviceCategory(str, Enum):
    """Категории устройств для FSM."""

    LIGHTING = "lighting"
    SWITCH_CONTROL = "switch_control"
    TEMPERATURE_SENSOR = "temperature_sensor"
    HUMIDITY_SENSOR = "humidity_sensor"
    MOTION_SENSOR = "motion_sensor"
    CLIMATE_CONTROL = "climate_control"
    VENTILATION = "ventilation"
    COVER_CONTROL = "cover_control"
    MONITORING_ONLY = "monitoring_only"


class BehaviorTemplate(str, Enum):
    """Существующие шаблоны платформы."""

    LIGHTING = "lighting"
    NIGHT_LIGHT = "night_light"
    CLIMATE_CONTROL = "climate_control"
    HUMIDITY_VENTILATION = "humidity_ventilation"


class DiscoveredDevice(BaseModel):
    """Обнаруженное устройство из Home Assistant."""

    entity_id: str
    domain: str
    name: str
    friendly_name: Optional[str] = None
    area_id: Optional[str] = None
    area_name: Optional[str] = None
    state: str = "unknown"
    attributes: dict[str, Any] = Field(default_factory=dict)
    category: DeviceCategory = DeviceCategory.MONITORING_ONLY
    suggested_behavior: Optional[str] = None
    auto_apply: bool = False  # Применить автоматически без подтверждения


class DeviceScanResult(BaseModel):
    """Результат сканирования."""

    scan_id: str
    scanned_at: datetime = Field(default_factory=datetime.now)
    total_devices: int
    devices: list[DiscoveredDevice] = Field(default_factory=list)
    by_domain: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_area: dict[str, int] = Field(default_factory=dict)


class DeviceSelection(BaseModel):
    """Выбор пользователя."""

    device_entity_id: str
    include: bool = True
    target_room: str
    target_room_name: Optional[str] = None
    behavior_template: Optional[str] = None
    behavior_params: dict[str, Any] = Field(default_factory=dict)


class BulkApplyRequest(BaseModel):
    """Массовое применение (для 200+ устройств)."""

    include_all: bool = False
    include_categories: list[DeviceCategory] = Field(default_factory=list)
    exclude_entities: list[str] = Field(default_factory=list)
    auto_apply_lighting: bool = True
    auto_apply_climate: bool = True
    auto_apply_ventilation: bool = True
    dry_run: bool = False
```

---

## 🔧 ШАГ 2: Классификатор (`src/core/discovery/classifier.py`)

```python
"""Device classifier - определяет категорию и назначает шаблоны."""

from __future__ import annotations

import re
from typing import Optional

from .models import DeviceCategory, BehaviorTemplate


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
    ) -> tuple[DeviceCategory, Optional[str], bool]:
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
    def extract_room_name(cls, entity_id: str) -> Optional[str]:
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
```

---

## 🔧 ШАГ 3: Тесты (`tests/test_discovery_classifier.py`)

```python
"""Tests for DeviceClassifier."""

import pytest
from src.core.discovery.classifier import DeviceClassifier
from src.core.discovery.models import DeviceCategory


class TestDeviceClassifier:
    def test_classify_light_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "light.kitchen_main", "light", {}
        )
        assert category == DeviceCategory.LIGHTING
        assert template == "lighting"
        assert auto_apply is True

    def test_classify_climate_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "climate.bedroom_ac", "climate", {}
        )
        assert category == DeviceCategory.CLIMATE_CONTROL
        assert template == "climate_control"
        assert auto_apply is True

    def test_classify_fan_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify("fan.bathroom_vent", "fan", {})
        assert category == DeviceCategory.VENTILATION
        assert template == "humidity_ventilation"
        assert auto_apply is True

    def test_classify_sensor_no_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "sensor.temperatura_v_teplitse_ogurtsy_humidity", "sensor", {}
        )
        assert category == DeviceCategory.TEMPERATURE_SENSOR
        assert template is None
        assert auto_apply is False

    def test_classify_plesen_monitoring(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "sensor.ogurtsy_plesen", "sensor", {}
        )
        assert category == DeviceCategory.MONITORING_ONLY
        assert template is None
        assert auto_apply is False

    def test_classify_water_depth_monitoring(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "sensor.datchik_urovnia_vody_v_bakakh_liquid_depth", "sensor", {}
        )
        assert category == DeviceCategory.MONITORING_ONLY

    def test_extract_room_name(self):
        assert DeviceClassifier.extract_room_name("light.kitchen_main") == "kitchen"
        assert DeviceClassifier.extract_room_name("binary_sensor.hallway_motion") == "hallway"
        assert DeviceClassifier.extract_room_name("sensor.living_room_temperature") == "living_room"

    def test_auto_apply_stats(self):
        class MockDevice:
            def __init__(self, auto_apply):
                self.auto_apply = auto_apply

        devices = [MockDevice(True), MockDevice(True), MockDevice(False)]
        stats = DeviceClassifier.get_auto_apply_count(devices)
        assert stats["auto_apply"] == 2
        assert stats["manual"] == 1
```

---

## 🔧 ШАГ 4: Сервис сканирования (`src/core/discovery/discovery_service.py`)

```python
"""Service for discovering 200+ devices from Home Assistant."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from loguru import logger

from .classifier import DeviceClassifier
from .models import DeviceScanResult, DiscoveredDevice, DeviceCategory, BulkApplyRequest

if TYPE_CHECKING:
    from src.adapters.ha_adapter import HAAdapter


SYSTEM_DOMAINS = {
    "automation",
    "script",
    "scene",
    "zone",
    "person",
    "sun",
    "weather",
    "device_tracker",
    "group",
    "input_boolean",
    "input_text",
    "input_number",
    "input_select",
    "input_datetime",
    "timer",
    "counter",
    "update",
    "persistent_notification",
    "hacs",
}

PAGE_SIZE = 25


class DeviceDiscoveryService:
    """Сканирует 200+ устройств с пагинацией и автоприменением шаблонов."""

    def __init__(self, ha_adapter: HAAdapter) -> None:
        self._ha_adapter = ha_adapter
        self._classifier = DeviceClassifier()
        logger.info("DeviceDiscoveryService initialized")

    async def scan_devices(
        self,
        page: int = 1,
        page_size: int = PAGE_SIZE,
        filter_domain: Optional[str] = None,
        filter_category: Optional[str] = None,
        filter_area: Optional[str] = None,
    ) -> dict:
        """Сканировать устройства с пагинацией."""
        ws_client = getattr(self._ha_adapter, "_ws_client", None)
        if ws_client is None or not getattr(ws_client, "connected", False):
            raise RuntimeError("HA WebSocket client not connected")

        all_states = await ws_client.get_states()

        # Фильтруем системные
        filtered = []
        for state_obj in all_states:
            entity_id = state_obj.get("entity_id", "")
            domain = entity_id.split(".")[0] if "." in entity_id else "unknown"
            if domain not in SYSTEM_DOMAINS:
                filtered.append(state_obj)

        # Классифицируем
        devices = []
        for state_obj in filtered:
            entity_id = state_obj.get("entity_id", "")
            domain = entity_id.split(".")[0]
            attributes = state_obj.get("attributes", {})

            category, suggested, auto_apply = self._classifier.classify(
                entity_id, domain, attributes
            )
            area_id = attributes.get("area_id") or self._classifier.extract_room_name(entity_id)

            device = DiscoveredDevice(
                entity_id=entity_id,
                domain=domain,
                name=attributes.get("friendly_name", entity_id),
                friendly_name=attributes.get("friendly_name"),
                area_id=area_id,
                state=state_obj.get("state", "unknown"),
                attributes=attributes,
                category=category,
                suggested_behavior=suggested,
                auto_apply=auto_apply,
            )
            devices.append(device)

        # Применяем фильтры
        if filter_domain:
            devices = [d for d in devices if d.domain == filter_domain]
        if filter_category:
            devices = [d for d in devices if d.category.value == filter_category]
        if filter_area:
            devices = [d for d in devices if d.area_id == filter_area]

        # Статистика
        by_domain = {}
        by_category = {}
        for d in devices:
            by_domain[d.domain] = by_domain.get(d.domain, 0) + 1
            by_category[d.category.value] = by_category.get(d.category.value, 0) + 1

        # Пагинация
        total = len(devices)
        total_pages = (total + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        page_devices = devices[start:end]

        # Автоприменение
        auto_stats = self._classifier.get_auto_apply_count(devices)

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "devices": [d.model_dump(mode="json") for d in page_devices],
            "by_domain": by_domain,
            "by_category": by_category,
            "auto_apply_stats": auto_stats,
        }

    async def bulk_apply(self, request: BulkApplyRequest, manifest_path: str) -> dict:
        """Массовое применение для 200+ устройств."""
        # Получаем все устройства
        scan_result = await self.scan_devices(page=1, page_size=10000)
        all_devices = scan_result["devices"]

        selections = []
        for device in all_devices:
            if device["entity_id"] in request.exclude_entities:
                continue

            include = False
            if request.include_all:
                include = True
            elif device["category"] in [c.value for c in request.include_categories]:
                include = True
            elif device["auto_apply"]:
                if device["category"] == "lighting" and request.auto_apply_lighting:
                    include = True
                elif device["category"] == "climate_control" and request.auto_apply_climate:
                    include = True
                elif device["category"] == "ventilation" and request.auto_apply_ventilation:
                    include = True

            if include:
                selections.append(
                    {
                        "device_entity_id": device["entity_id"],
                        "include": True,
                        "target_room": device["area_id"] or "unassigned",
                        "behavior_template": device["suggested_behavior"],
                    }
                )

        if request.dry_run:
            return {"dry_run": True, "would_add": len(selections)}

        # Применяем к манифесту
        import yaml
        from datetime import datetime

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f) or {}

        rooms = manifest.setdefault("rooms", [])
        added_count = 0

        for sel in selections:
            entity_id = sel["device_entity_id"]
            target_room = sel["target_room"]
            behavior_template = sel["behavior_template"]

            # Найти или создать комнату
            room = next((r for r in rooms if r["id"] == target_room), None)
            if room is None:
                room = {
                    "id": target_room,
                    "name": target_room.replace("_", " ").title(),
                    "sensors": {},
                    "devices": [],
                }
                rooms.append(room)

            # Найти оригинальное устройство для категории
            device_obj = next((d for d in all_devices if d["entity_id"] == entity_id), None)
            if not device_obj:
                continue

            if device_obj["category"] in ("temperature_sensor", "humidity_sensor", "motion_sensor"):
                sensor_type = device_obj["category"].replace("_sensor", "")
                room.setdefault("sensors", {})[sensor_type] = entity_id
            else:
                device_entry = {"id": entity_id, "type": device_obj["domain"]}
                if behavior_template:
                    device_entry["behaviors"] = [
                        {
                            "template": behavior_template,
                            "priority": 10,
                            "params": {},
                        }
                    ]
                room.setdefault("devices", []).append(device_entry)

            added_count += 1

        # Backup
        backup_path = f"{manifest_path}.bak.{datetime.now():%Y%m%d_%H%M%S}"
        with open(backup_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

        # Сохраняем
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False, sort_keys=False)

        # Hot reload
        await self._hot_reload_fsm(manifest)

        logger.info(f"Bulk apply: {added_count} devices added. Backup: {backup_path}")
        return {"success": True, "devices_added": added_count, "backup_path": backup_path}

    async def _hot_reload_fsm(self, manifest: dict):
        """Пересоздать FSM definitions после обновления манифеста."""
        try:
            from src.core.manifest_generator import ManifestAutomationGenerator

            generator = ManifestAutomationGenerator(manifest)
            result = generator.generate_all()

            from src.core.container import container

            fsm_engine = container.fsm_engine
            event_router = container.event_router

            all_definitions = (
                result.lighting_definitions
                + result.climate_definitions
                + result.ventilation_definitions
            )
            all_mappings = (
                result.lighting_mappings + result.climate_mappings + result.ventilation_mappings
            )

            for definition in all_definitions:
                fsm_engine.register_definition(definition)

            for mapping in all_mappings:
                event_router.add_mapping(mapping)

            logger.info(f"Hot reload: registered {len(all_definitions)} FSM definitions")
        except Exception as e:
            logger.error(f"Hot reload failed: {e}")
```

---

## 🔧 ШАГ 5: `__init__.py` (`src/core/discovery/__init__.py`)

```python
"""Device Discovery module."""

from .models import (
    DeviceCategory,
    DiscoveredDevice,
    DeviceScanResult,
    DeviceSelection,
    BulkApplyRequest,
)
from .classifier import DeviceClassifier
from .discovery_service import DeviceDiscoveryService

__all__ = [
    "DeviceCategory",
    "DiscoveredDevice",
    "DeviceScanResult",
    "DeviceSelection",
    "BulkApplyRequest",
    "DeviceClassifier",
    "DeviceDiscoveryService",
]
```

---

## 🔧 ШАГ 6: Подключение в `src/webui/app.py`

Добавить после создания `app`:

```python
# После создания app:
from .routes_discovery import init_discovery_routes, router as discovery_router

app.include_router(discovery_router)


@app.on_event("startup")
async def init_discovery():
    from src.core.container import container

    init_discovery_routes(container.ha_adapter, manifest_path)
```

---

## ✅ КРИТЕРИИ ГОТОВНОСТИ

- [ ] `pytest tests/test_discovery_classifier.py -v` — все тесты проходят
- [ ] Кнопка "Scan" запускает сканирование и показывает прогресс
- [ ] Для 200+ устройств работает пагинация (по 25 на страницу)
- [ ] Фильтры по домену/комнате/категории работают
- [ ] Свет, климат, вентиляция **автоматически** получают шаблоны
- [ ] Кнопка "Apply All" применяет все авто-шаблоны за один клик
- [ ] После применения в логах исчезает `No FSM definition found`
- [ ] Мобильное приложение HA отображает изменения

### Проверка на реальных данных

Для 200+ устройств пользователя:
- Сканирование должно занять < 10 секунд
- Автоприменение света/климата/вентиляции — за 1 клик
- Мониторинговые устройства (датчики) — добавляются в `sensors` комнаты

---

## 📋 ПЛАН РЕАЛИЗАЦИИ

| # | Шаг | Приоритет |
|---|-----|-----------|
| 1 | Создать `src/core/discovery/models.py` | P0 |
| 2 | Создать `src/core/discovery/classifier.py` | P0 |
| 3 | Создать `src/core/discovery/__init__.py` | P0 |
| 4 | Создать `tests/test_discovery_classifier.py` | P0 |
| 5 | Запустить тесты: `pytest tests/test_discovery_classifier.py -v` | P0 |
| 6 | Создать `src/core/discovery/discovery_service.py` | P0 |
| 7 | Создать `src/webui/routes_discovery.py` | P0 |
| 8 | Создать `src/webui/templates/discovery.html` | P0 |
| 9 | Подключить в `app.py` | P0 |
| 10 | Тест на реальных 200+ устройствах | P0 |

---

## ⚠️ ВАЖНО

1. **НЕ создавать новый WebSocket client** — использовать существующий `HAAdapter._ws_client`
2. **НЕ переписывать `ManifestAutomationGenerator`** — использовать для hot reload
3. **Сохранить dark theme** Bootstrap 5
4. **Русский язык** в интерфейсе
5. **Пагинация обязательна** для 200+ устройств
6. **Прогресс-бар** при сканировании
7. **Автоприменение** шаблонов для света/климата/вентиляции

---

## 🚀 НАЧАТЬ С

1. Создать структуру: `mkdir -p src/core/discovery tests`
2. Создать `src/core/discovery/models.py` (код из Шага 1)
3. Создать `src/core/discovery/classifier.py` (код из Шага 2)
4. Создать `src/core/discovery/__init__.py` (код из Шага 5)
5. Создать `tests/test_discovery_classifier.py` (код из Шага 3)
6. Запустить: `pytest tests/test_discovery_classifier.py -v`
7. **Показать результат** перед продолжением
