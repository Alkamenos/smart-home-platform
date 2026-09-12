"""Tests for manifest loading with Pydantic v2 models."""

import pytest
from pydantic import ValidationError

from src.smart_home.core.models.manifest import (
    Manifest,
    LightMotionDevice,
    ClimateHysteresisDevice,
    VentilationHumidityDevice,
    load_manifest,
)


class TestManifestLoading:
    """Тесты загрузки валидного манифеста."""

    def test_load_valid_manifest(self, tmp_path):
        """Успешная загрузка валидного YAML манифеста."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: kitchen
    name: Kitchen
    floor: 1
devices:
  - type: light_motion
    id: light.kitchen
    name: Kitchen Light
    room: kitchen
    motion_sensor: binary_sensor.kitchen_motion
    motion_timeout_sec: 300
    schedule: "07:00-23:00"
  - type: climate_hysteresis
    id: climate.kitchen
    name: Kitchen Climate
    room: kitchen
    sensor: sensor.kitchen_temperature
    target: 22.0
    hysteresis: 0.5
    modes:
      - heat
      - cool
  - type: ventilation_humidity
    id: fan.bathroom
    name: Bathroom Fan
    room: bathroom
    humidity_sensor: sensor.bathroom_humidity
    humidity_threshold: 65
    timeout_sec: 1800
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        manifest = load_manifest(str(manifest_file))

        assert manifest.version == 1
        assert manifest.instance.id == "test_house"
        assert len(manifest.zones) == 1
        assert len(manifest.devices) == 3

    def test_load_light_motion_device(self, tmp_path):
        """Загрузка устройства освещения с датчиком движения."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: kitchen
    name: Kitchen
    floor: 1
devices:
  - type: light_motion
    id: light.kitchen
    name: Kitchen Light
    room: kitchen
    motion_sensor: binary_sensor.kitchen_motion
    motion_timeout_sec: 300
    schedule: "07:00-23:00"
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        manifest = load_manifest(str(manifest_file))

        assert len(manifest.devices) == 1
        device = manifest.devices[0]
        assert isinstance(device, LightMotionDevice)
        assert device.type == "light_motion"
        assert device.id == "light.kitchen"
        assert device.motion_sensor == "binary_sensor.kitchen_motion"
        assert device.motion_timeout_sec == 300
        assert device.schedule == "07:00-23:00"

    def test_load_climate_hysteresis_device(self, tmp_path):
        """Загрузка климатического устройства с гистерезисом."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: kitchen
    name: Kitchen
    floor: 1
devices:
  - type: climate_hysteresis
    id: climate.kitchen
    name: Kitchen Climate
    room: kitchen
    sensor: sensor.kitchen_temperature
    target: 22.0
    hysteresis: 0.5
    modes:
      - heat
      - cool
      - auto
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        manifest = load_manifest(str(manifest_file))

        assert len(manifest.devices) == 1
        device = manifest.devices[0]
        assert isinstance(device, ClimateHysteresisDevice)
        assert device.type == "climate_hysteresis"
        assert device.id == "climate.kitchen"
        assert device.sensor == "sensor.kitchen_temperature"
        assert device.target == 22.0
        assert device.hysteresis == 0.5
        assert device.modes == ["heat", "cool", "auto"]

    def test_load_ventilation_humidity_device(self, tmp_path):
        """Загрузка вентиляционного устройства с контролем влажности."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: bathroom
    name: Bathroom
    floor: 1
devices:
  - type: ventilation_humidity
    id: fan.bathroom
    name: Bathroom Fan
    room: bathroom
    humidity_sensor: sensor.bathroom_humidity
    humidity_threshold: 65
    timeout_sec: 1800
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        manifest = load_manifest(str(manifest_file))

        assert len(manifest.devices) == 1
        device = manifest.devices[0]
        assert isinstance(device, VentilationHumidityDevice)
        assert device.type == "ventilation_humidity"
        assert device.id == "fan.bathroom"
        assert device.humidity_sensor == "sensor.bathroom_humidity"
        assert device.humidity_threshold == 65
        assert device.timeout_sec == 1800

    def test_load_from_fixture(self):
        """Загрузка манифеста из fixture файла."""
        manifest = load_manifest("tests/fixtures/valid_manifest.yaml")

        assert manifest.version == 1
        assert manifest.instance.id == "leonids_house"
        assert len(manifest.zones) == 4
        assert len(manifest.devices) == 6


class TestManifestValidationErrors:
    """Тесты ошибок валидации манифеста."""

    def test_invalid_device_type(self, tmp_path):
        """Ошибка при неизвестном типе устройства."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: kitchen
    name: Kitchen
    floor: 1
devices:
  - type: invalid_type_xyz
    id: light.kitchen
    name: Kitchen Light
    room: kitchen
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        with pytest.raises(ValidationError) as exc_info:
            load_manifest(str(manifest_file))

        error = exc_info.value
        assert "invalid_type_xyz" in str(error) or "type" in str(error).lower()

    def test_missing_required_field(self, tmp_path):
        """Ошибка при отсутствии обязательного поля."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: kitchen
    name: Kitchen
    floor: 1
devices:
  - type: light_motion
    id: light.kitchen
    room: kitchen
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        with pytest.raises(ValidationError) as exc_info:
            load_manifest(str(manifest_file))

        error = exc_info.value
        # Проверяем, что ошибка указывает на missing field
        assert "name" in str(error).lower() or "missing" in str(error).lower() or "field" in str(error).lower()

    def test_missing_motion_sensor_for_light(self, tmp_path):
        """Ошибка при отсутствии motion_sensor для light_motion устройства."""
        manifest_content = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2026-01-01'
zones:
  - id: kitchen
    name: Kitchen
    floor: 1
devices:
  - type: light_motion
    id: light.kitchen
    name: Kitchen Light
    room: kitchen
    motion_timeout_sec: 300
    schedule: "07:00-23:00"
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    away_mode_enabled: true
    manual_lockout_min: 30
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""
        manifest_file = tmp_path / "manifest.yaml"
        manifest_file.write_text(manifest_content)

        with pytest.raises(ValidationError) as exc_info:
            load_manifest(str(manifest_file))

        error = exc_info.value
        assert "motion_sensor" in str(error).lower() or "missing" in str(error).lower()

    def test_load_invalid_type_fixture(self):
        """Загрузка манифеста с невалидным типом из fixture."""
        with pytest.raises(ValidationError):
            load_manifest("tests/fixtures/invalid_manifest_bad_type.yaml")

    def test_load_missing_field_fixture(self):
        """Загрузка манифеста с отсутствующим полем из fixture."""
        with pytest.raises(ValidationError):
            load_manifest("tests/fixtures/invalid_manifest_missing_field.yaml")

    def test_file_not_found(self):
        """Ошибка при отсутствии файла."""
        with pytest.raises(FileNotFoundError):
            load_manifest("nonexistent/path/manifest.yaml")
