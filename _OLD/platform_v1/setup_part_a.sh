#!/usr/bin/env bash
# Bootstrap Части A: схема + валидатор + CLI + тесты
set -e

echo "==> Проверка версии Python (нужен 3.11+)"
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    Найдено: python $PYVER"
python3 -c 'import sys; exit(0 if sys.version_info >= (3,11) else 1)' \
  || { echo "✗ Нужен Python 3.11+"; exit 1; }

echo "==> Создание структуры директорий"
mkdir -p shplatform/schema shplatform/validator shplatform/loader cli manifests/templates ha/pyscript tests

# ====================== pyproject.toml ======================
cat > pyproject.toml << 'EOF'
[project]
name = "smart-home-platform"
version = "0.1.0"
description = "Data-driven smart home platform for Home Assistant"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "PyYAML>=6.0",
    "click>=8.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov"]

[project.scripts]
shplatform = "cli.main:cli"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["shplatform*", "cli*"]
EOF

# ====================== shplatform/__init__.py ======================
cat > shplatform/__init__.py << 'EOF'
"""Ядро платформы умного дома."""
EOF

# ====================== schema/manifest.py ======================
cat > shplatform/schema/manifest.py << 'EOF'
"""Корневая модель манифеста и конфигурация инстанса."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .devices import DevicesConfig
from .features import FeaturesConfig
from .globals_cfg import GlobalsConfig
from .integrations import IntegrationsConfig, DashboardConfig


class InstanceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    customer: str | None = None
    installed_date: str | None = None
    platform_version: str | None = None
    notes: str | None = None


class InstanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9_]+$", description="Уникальный ID, только snake_case")
    name: str
    timezone: str
    locale: str = "ru-RU"
    version: str = Field(..., description="Версия манифеста для миграций")
    metadata: InstanceMetadata = Field(default_factory=InstanceMetadata)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance: InstanceConfig
    devices: DevicesConfig
    features: FeaturesConfig
    globals: GlobalsConfig
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
EOF

# ====================== schema/devices.py ======================
cat > shplatform/schema/devices.py << 'EOF'
"""Модели устройств. Все entity_id живут ТОЛЬКО здесь."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeviceBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(..., pattern=r"^[a-z0-9_]+$", description="Логический ID устройства")


class HybridSwitchMode(BaseModel):
    model_config = ConfigDict(extra="allow")
    physical_override: dict | None = None
    button_actions: dict[str, dict] | None = None


class HybridSwitch(DeviceBase):
    adapter: str = Field(..., description="Имя адаптера, напр. z2m_aqara_h1m")
    relay_entity: str
    button_event_sensor: str | None = None
    initial_mode: str = "control_relay"
    modes: dict[str, HybridSwitchMode] = Field(default_factory=dict)
    auto_mode_switch: list[dict] = Field(default_factory=list)


class Light(DeviceBase):
    entity: str
    type: str = "zigbee_switch"


class Sensor(DeviceBase):
    entity: str
    role: str | None = None


class Actuator(DeviceBase):
    entity: str
    type: str = Field(..., description="relay | climate_device | recuperator | ...")
    safety_max_temp_entity: str | None = None
    safety_max_temp: float | None = None
    min_cycle_minutes: int | None = None


class Valve(DeviceBase):
    entity: str
    type: str = "zigbee_valve"


class DevicesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hybrid_switches: list[HybridSwitch] = Field(default_factory=list)
    lights: list[Light] = Field(default_factory=list)
    sensors: list[Sensor] = Field(default_factory=list)
    actuators: list[Actuator] = Field(default_factory=list)
    valves: list[Valve] = Field(default_factory=list)

    def all_ids(self) -> set[str]:
        ids: set[str] = set()
        for group in (self.hybrid_switches, self.lights, self.sensors,
                      self.actuators, self.valves):
            ids.update(d.id for d in group)
        return ids

    def by_id(self) -> dict[str, DeviceBase]:
        mapping: dict[str, DeviceBase] = {}
        for group in (self.hybrid_switches, self.lights, self.sensors,
                      self.actuators, self.valves):
            for d in group:
                mapping[d.id] = d
        return mapping
EOF

# ====================== schema/features.py ======================
cat > shplatform/schema/features.py << 'EOF'
"""Модели фич. Ссылаются на устройства ТОЛЬКО по id (через *_ref)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True


class LightingZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    device_refs: list[str] = Field(default_factory=list)
    schedule_calendar: str | None = None
    overrides: list[str] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)


class Lighting(FeatureBase):
    zones: list[LightingZone] = Field(default_factory=list)


class IrrigationZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    valve_ref: str | None = None
    schedule_calendar: str | None = None
    moisture_sensor_ref: str | None = None
    overrides: list[str] = Field(default_factory=list)
    conditions: dict = Field(default_factory=dict)


class Irrigation(FeatureBase):
    zones: list[IrrigationZone] = Field(default_factory=list)


class ClimateActuatorRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    ref: str
    role: str
    priority: int


class ClimateSafety(BaseModel):
    model_config = ConfigDict(extra="allow")
    floor_max_temp_ref: str | None = None
    floor_max_temp: float | None = None
    sensor_unavailable_timeout_min: int = 5
    emergency_off_on_sensor_loss: bool = True


class ClimateZone(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    temp_sensor_ref: str | None = None
    setpoints: dict = Field(default_factory=dict)
    actuators: list[ClimateActuatorRef] = Field(default_factory=list)
    safety: ClimateSafety | None = None


class SeasonDetection(BaseModel):
    model_config = ConfigDict(extra="allow")
    mode: str = "auto"
    heating_threshold: float = 15
    cooling_threshold: float = 20
    hysteresis_hours: int = 24


class Climate(FeatureBase):
    season_detection: SeasonDetection = Field(default_factory=SeasonDetection)
    zones: list[ClimateZone] = Field(default_factory=list)


class FeaturesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lighting: Lighting = Field(default_factory=Lighting)
    irrigation: Irrigation = Field(default_factory=Irrigation)
    climate: Climate = Field(default_factory=Climate)
    security: FeatureBase = Field(default_factory=lambda: FeatureBase(enabled=False))
    energy: FeatureBase = Field(default_factory=lambda: FeatureBase(enabled=False))
EOF

# ====================== schema/globals_cfg.py ======================
cat > shplatform/schema/globals_cfg.py << 'EOF'
"""Глобальные режимы и override-политики."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GlobalMode(BaseModel):
    model_config = ConfigDict(extra="allow")
    entity: str
    affects: list[str] = Field(default_factory=list)


class OverridePolicy(BaseModel):
    model_config = ConfigDict(extra="allow")
    priority: str = "lowest"
    duration: str | None = None
    default_timeout_min: int | None = None


class GlobalsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modes: dict[str, GlobalMode] = Field(default_factory=dict)
    override_policy: dict[str, OverridePolicy] = Field(default_factory=dict)
    evaluation_intervals: dict[str, int] = Field(default_factory=dict)
EOF

# ====================== schema/integrations.py ======================
cat > shplatform/schema/integrations.py << 'EOF'
"""Интеграции и генерация дашборда. Зарезервированы для расширения."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Integration(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False


class IntegrationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yandex_dialogs: Integration = Field(default_factory=Integration)
    telegram_bot: Integration = Field(default_factory=Integration)
    mqtt_broker: Integration = Field(default_factory=Integration)


class DashboardPage(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    sections: list[dict] = Field(default_factory=list)


class DashboardConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    template_engine: str = "jinja2"
    templates_dir: str = "templates/dashboards/"
    pages: list[DashboardPage] = Field(default_factory=list)
EOF

# ====================== schema/__init__.py ======================
cat > shplatform/schema/__init__.py << 'EOF'
from .manifest import Manifest, InstanceConfig, InstanceMetadata
from .devices import (
    DevicesConfig, DeviceBase, HybridSwitch, Light, Sensor, Actuator, Valve,
)
from .features import (
    FeaturesConfig, Lighting, Irrigation, Climate,
    LightingZone, IrrigationZone, ClimateZone, ClimateActuatorRef,
)
from .globals_cfg import GlobalsConfig, GlobalMode, OverridePolicy
from .integrations import IntegrationsConfig, DashboardConfig

__all__ = [
    "Manifest", "InstanceConfig", "InstanceMetadata",
    "DevicesConfig", "DeviceBase", "HybridSwitch", "Light", "Sensor",
    "Actuator", "Valve",
    "FeaturesConfig", "Lighting", "Irrigation", "Climate",
    "LightingZone", "IrrigationZone", "ClimateZone", "ClimateActuatorRef",
    "GlobalsConfig", "GlobalMode", "OverridePolicy",
    "IntegrationsConfig", "DashboardConfig",
]
EOF

# ====================== validator/cross_ref.py ======================
cat > shplatform/validator/cross_ref.py << 'EOF'
"""Проверки связности манифеста (cross-references)."""
from __future__ import annotations

from dataclasses import dataclass, field

from shplatform.schema import Manifest


@dataclass
class ValidationIssue:
    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.path}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, path: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, code, message))


def validate_manifest(manifest: Manifest) -> ValidationReport:
    report = ValidationReport()
    device_ids = manifest.devices.all_ids()

    _check_duplicate_device_ids(manifest, report)
    _check_lighting_refs(manifest, device_ids, report)
    _check_irrigation_refs(manifest, device_ids, report)
    _check_climate_refs(manifest, device_ids, report)
    _check_climate_priorities(manifest, report)

    return report


def _check_duplicate_device_ids(manifest: Manifest, report: ValidationReport) -> None:
    seen: dict[str, int] = {}
    for group in (manifest.devices.hybrid_switches, manifest.devices.lights,
                  manifest.devices.sensors, manifest.devices.actuators,
                  manifest.devices.valves):
        for dev in group:
            seen[dev.id] = seen.get(dev.id, 0) + 1

    for did, count in seen.items():
        if count > 1:
            report.add(
                f"devices.{did}", "DUPLICATE_DEVICE_ID",
                f"Device id '{did}' встречается {count} раз. ID должны быть уникальны.",
            )


def _check_lighting_refs(manifest: Manifest, device_ids: set[str],
                         report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.lighting.zones):
        base = f"features.lighting.zones[{i}]"
        for ref in zone.device_refs:
            if ref not in device_ids:
                report.add(f"{base}.device_refs", "UNKNOWN_DEVICE_REF",
                           f"'{ref}' не найден в devices")


def _check_irrigation_refs(manifest: Manifest, device_ids: set[str],
                           report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.irrigation.zones):
        base = f"features.irrigation.zones[{i}]"
        if zone.valve_ref and zone.valve_ref not in device_ids:
            report.add(f"{base}.valve_ref", "UNKNOWN_DEVICE_REF",
                       f"'{zone.valve_ref}' не найден в devices")
        if zone.moisture_sensor_ref and zone.moisture_sensor_ref not in device_ids:
            report.add(f"{base}.moisture_sensor_ref", "UNKNOWN_DEVICE_REF",
                       f"'{zone.moisture_sensor_ref}' не найден в devices")


def _check_climate_refs(manifest: Manifest, device_ids: set[str],
                        report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.climate.zones):
        base = f"features.climate.zones[{i}]"
        if zone.temp_sensor_ref and zone.temp_sensor_ref not in device_ids:
            report.add(f"{base}.temp_sensor_ref", "UNKNOWN_DEVICE_REF",
                       f"'{zone.temp_sensor_ref}' не найден в devices")
        for j, act in enumerate(zone.actuators):
            if act.ref not in device_ids:
                report.add(f"{base}.actuators[{j}].ref", "UNKNOWN_DEVICE_REF",
                           f"'{act.ref}' не найден в devices")


def _check_climate_priorities(manifest: Manifest, report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.climate.zones):
        base = f"features.climate.zones[{i}].actuators"
        priorities: dict[int, str] = {}
        for act in zone.actuators:
            if act.priority in priorities:
                report.add(
                    base, "DUPLICATE_PRIORITY",
                    f"Приоритет {act.priority} занят '{priorities[act.priority]}' "
                    f"и '{act.ref}'. Приоритеты в зоне должны быть уникальны.",
                )
            else:
                priorities[act.priority] = act.ref
EOF

cat > shplatform/validator/__init__.py << 'EOF'
from .cross_ref import validate_manifest, ValidationReport, ValidationIssue
__all__ = ["validate_manifest", "ValidationReport", "ValidationIssue"]
EOF

cat > shplatform/loader/__init__.py << 'EOF'
EOF

# ====================== cli/main.py ======================
cat > cli/__init__.py << 'EOF'
EOF

cat > cli/main.py << 'EOF'
"""CLI платформы: валидация, генерация JSON Schema, создание инстанса."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml
from pydantic import ValidationError

from shplatform.schema import Manifest
from shplatform.validator import validate_manifest


def _load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise click.ClickException(f"Файл не найден: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    try:
        manifest = Manifest.model_validate(raw)
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msgs.append(f"  {loc}: {err['msg']}")
        raise click.ClickException(
            "Структурные ошибки манифеста:\n" + "\n".join(msgs)
        )
    return manifest


@click.group()
def cli() -> None:
    """Инструменты платформы умного дома."""


@cli.command()
@click.argument("manifest_path", type=click.Path(exists=False))
def validate(manifest_path: str) -> None:
    """Проверить манифест: структура + cross-references."""
    path = Path(manifest_path)
    manifest = _load_manifest(path)

    report = validate_manifest(manifest)
    if report.ok:
        click.secho(f"OK: Манифест '{path}' корректен", fg="green")
        return

    click.secho(f"FAIL: Найдено проблем: {len(report.issues)}", fg="red")
    for issue in report.issues:
        click.echo(f"  {issue}")
    sys.exit(1)


@cli.command()
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Сохранить JSON Schema в файл")
def schema(output: str | None) -> None:
    """Вывести JSON Schema манифеста."""
    js = Manifest.model_json_schema()
    text = json.dumps(js, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.secho(f"OK: JSON Schema сохранена в {output}", fg="green")
    else:
        click.echo(text)


if __name__ == "__main__":
    cli()
EOF

# ====================== manifests/ivanov_dacha.yaml ======================
cat > manifests/ivanov_dacha.yaml << 'EOF'
instance:
  id: ivanov_dacha
  name: "Дача Ивановых"
  timezone: Europe/Moscow
  locale: ru-RU
  version: "1.0.0"
  metadata:
    customer: "Иванов А.С."
    platform_version: "0.1.0"

devices:
  hybrid_switches:
    - id: lr_main_switch
      adapter: z2m_aqara_h1m
      z2m_friendly_name: living_room_h1m
      relay_entity: switch.living_room_h1m_l1
      button_event_sensor: sensor.living_room_h1m_action
      initial_mode: control_relay

  lights:
    - id: lr_main
      entity: light.living_room_main
      type: zigbee_dimmer
    - id: terrace
      entity: light.terrace_main
      type: zigbee_switch

  sensors:
    - id: outdoor_temp
      entity: sensor.outdoor_temperature
      role: climate_reference
    - id: lr_temp
      entity: sensor.living_room_temp
      role: climate_zone_lr
    - id: lr_floor_temp
      entity: sensor.floor_temp_lr
      role: safety_floor_lr

  actuators:
    - id: floor_heating_lr
      entity: switch.floor_heating_lr
      type: relay
      safety_max_temp_entity: sensor.floor_temp_lr
      safety_max_temp: 28
      min_cycle_minutes: 30
    - id: convector_lr
      entity: switch.convector_lr
      type: relay
      min_cycle_minutes: 5
    - id: ac_lr
      entity: climate.ac_living_room
      type: climate_device
    - id: vakio_lr
      entity: fan.vakio_base_lr
      type: recuperator

  valves:
    - id: front_lawn_valve
      entity: switch.valve_front_zb
      type: zigbee_valve

features:
  lighting:
    enabled: true
    zones:
      - id: lr_lighting
        device_refs: [lr_main]
        schedule_calendar: calendar.lighting_lr
      - id: terrace_lighting
        device_refs: [terrace]

  irrigation:
    enabled: true
    zones:
      - id: front_lawn
        valve_ref: front_lawn_valve
        schedule_calendar: calendar.irrigation_front
        conditions:
          min_moisture: 30
          rain_delay_hours: 6

  climate:
    enabled: true
    season_detection:
      mode: auto
      heating_threshold: 15
      cooling_threshold: 20
      hysteresis_hours: 24
    zones:
      - id: lr_climate
        temp_sensor_ref: lr_temp
        setpoints:
          heat: { source: input_number.lr_heat_target }
          cool: { source: input_number.lr_cool_target }
          deadband: 0.5
        actuators:
          - { ref: vakio_lr, role: free_cooling, priority: 1 }
          - { ref: floor_heating_lr, role: primary_heat, priority: 2 }
          - { ref: convector_lr, role: secondary_heat, priority: 3 }
          - { ref: ac_lr, role: primary_cool, priority: 4 }
        safety:
          floor_max_temp_ref: lr_floor_temp
          floor_max_temp: 28

globals:
  modes:
    party:
      entity: input_boolean.party_mode
      affects: [lighting, climate]
  override_policy:
    physical_switch: { priority: highest, duration: indefinite }
    voice_assistant: { priority: medium, default_timeout_min: 120 }
  evaluation_intervals:
    climate_sec: 60
    lighting_sec: 30

integrations:
  yandex_dialogs: { enabled: false }
  telegram_bot: { enabled: false }

dashboard:
  pages:
    - id: main
      title: "Главная"
      sections:
        - { feature: climate }
        - { feature: lighting }
EOF

# ====================== tests/test_schema.py ======================
cat > tests/conftest.py << 'EOF'
EOF

cat > tests/test_schema.py << 'EOF'
import pytest
import yaml
from pydantic import ValidationError

from shplatform.schema import Manifest
from shplatform.validator import validate_manifest


@pytest.fixture
def good_manifest_path():
    return "manifests/ivanov_dacha.yaml"


def _load(path):
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    return Manifest.model_validate(raw)


def test_good_manifest_is_valid(good_manifest_path):
    manifest = _load(good_manifest_path)
    report = validate_manifest(manifest)
    assert report.ok, "\n".join(str(i) for i in report.issues)


def test_unknown_ref_is_caught(good_manifest_path):
    manifest = _load(good_manifest_path)
    manifest.features.lighting.zones[0].device_refs = ["nonexistent_light"]
    report = validate_manifest(manifest)
    assert not report.ok
    assert any(i.code == "UNKNOWN_DEVICE_REF" for i in report.issues)


def test_duplicate_priority_is_caught(good_manifest_path):
    manifest = _load(good_manifest_path)
    zone = manifest.features.climate.zones[0]
    zone.actuators[1].priority = zone.actuators[0].priority
    report = validate_manifest(manifest)
    assert any(i.code == "DUPLICATE_PRIORITY" for i in report.issues)


def test_bad_instance_id_rejected():
    raw = {
        "instance": {"id": "Bad-ID!", "name": "x", "timezone": "UTC", "version": "1"},
        "devices": {}, "features": {}, "globals": {},
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)
EOF

echo "==> Создание виртуального окружения"
python3 -m venv .venv
source .venv/bin/activate

echo "==> Установка зависимостей (может занять минуту)"
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"

echo ""
echo "==> Запуск валидации примера"
shplatform validate manifests/ivanov_dacha.yaml

echo ""
echo "==> Генерация JSON Schema"
shplatform schema -o schema.json

echo ""
echo "==> Запуск тестов"
pytest tests/ -v

echo ""
echo "==> Готово. Активация окружения: source .venv/bin/activate"