"""Tests for manifest loading and validation."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from src.smart_home.core.models.manifest import load_manifest, Manifest


VALID_MANIFEST_YAML = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2024-01-01'
devices:
  lighting:
  - id: light.kitchen
    name: Kitchen Light
    room: kitchen
    motion_sensor: sensor.kitchen_motion
    motion_timeout_sec: 300
    schedule: "07:00-23:00"
  climate:
  - id: climate.living_room
    name: Living Room Climate
    room: living_room
    sensor: sensor.living_room_temp
    target: 22.0
    hysteresis: 0.5
    modes:
    - heat
    - cool
  ventilation:
  - id: fan.bathroom
    name: Bathroom Fan
    room: bathroom
    humidity_sensor: sensor.bathroom_humidity
    humidity_threshold: 65
    timeout_sec: 1800
zones:
- id: kitchen
  name: Kitchen
  floor: 1
automation_rules:
  lighting:
    schedule_enabled: true
dashboard:
  title: Test Dashboard
  show_history: true
  show_climate: true
  show_motion_sensors: true
  history_days: 7
"""

INVALID_TYPE_YAML = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2024-01-01'
devices:
  lighting:
  - id: light.kitchen
    name: Kitchen Light
    room: kitchen
    motion_sensor: sensor.kitchen_motion
    motion_timeout_sec: 300
    # Опечатка в типе устройства (будет добавлен автоматически, но проверим другие поля)
"""

MISSING_REQUIRED_FIELD_YAML = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2024-01-01'
devices:
  climate:
  - id: climate.living_room
    name: Living Room Climate
    room: living_room
    # Отсутствует обязательное поле sensor
    target: 22.0
    hysteresis: 0.5
    modes:
    - heat
"""

INVALID_DISCRIMINATOR_YAML = """
version: 1
instance:
  id: test_house
  name: Test House
  owner: Test Owner
  created_at: '2024-01-01'
devices:
- id: light.kitchen
  name: Kitchen Light
  room: kitchen
  type: invalid_type_unknown
  motion_sensor: sensor.kitchen_motion
  motion_timeout_sec: 300
"""


class TestManifestLoading:
    """Тесты загрузки валидного манифеста."""

    def test_load_valid_manifest(self):
        """Проверка загрузки валидного YAML манифеста."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(VALID_MANIFEST_YAML)
            f.flush()
            temp_path = f.name

        try:
            manifest = load_manifest(temp_path)
            
            assert isinstance(manifest, Manifest)
            assert manifest.version == 1
            assert manifest.instance.id == "test_house"
            assert manifest.instance.name == "Test House"
            assert len(manifest.devices) == 3
            
            # Проверка типов устройств
            device_types = [d.type for d in manifest.devices]
            assert "light_motion" in device_types
            assert "climate_hysteresis" in device_types
            assert "ventilation_humidity" in device_types
            
            # Проверка зон
            assert len(manifest.zones) == 1
            assert manifest.zones[0].id == "kitchen"
            
            # Проверка дашборда
            assert manifest.dashboard is not None
            assert manifest.dashboard.title == "Test Dashboard"
            
        finally:
            Path(temp_path).unlink()

    def test_device_polymorphism(self):
        """Проверка корректного определения типов устройств."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(VALID_MANIFEST_YAML)
            f.flush()
            temp_path = f.name

        try:
            manifest = load_manifest(temp_path)
            
            light_devices = [d for d in manifest.devices if d.type == "light_motion"]
            climate_devices = [d for d in manifest.devices if d.type == "climate_hysteresis"]
            vent_devices = [d for d in manifest.devices if d.type == "ventilation_humidity"]
            
            assert len(light_devices) == 1
            assert len(climate_devices) == 1
            assert len(vent_devices) == 1
            
            # Проверка специфичных полей
            light = light_devices[0]
            assert light.motion_sensor == "sensor.kitchen_motion"
            assert light.motion_timeout_sec == 300
            assert light.schedule == "07:00-23:00"
            
            climate = climate_devices[0]
            assert climate.sensor == "sensor.living_room_temp"
            assert climate.target == 22.0
            assert climate.hysteresis == 0.5
            assert "heat" in climate.modes
            
            vent = vent_devices[0]
            assert vent.humidity_sensor == "sensor.bathroom_humidity"
            assert vent.humidity_threshold == 65
            assert vent.timeout_sec == 1800
            
        finally:
            Path(temp_path).unlink()


class TestManifestValidationErrors:
    """Тесты обработки ошибок валидации."""

    def test_invalid_discriminator_type(self):
        """Проверка ошибки при неизвестном типе устройства."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(INVALID_DISCRIMINATOR_YAML)
            f.flush()
            temp_path = f.name

        try:
            with pytest.raises(ValidationError) as exc_info:
                load_manifest(temp_path)
            
            # Проверяем, что ошибка содержит информацию о дискриминаторе
            error_str = str(exc_info.value)
            assert "type" in error_str.lower() or "discriminator" in error_str.lower()
            
        finally:
            Path(temp_path).unlink()

    def test_missing_required_field(self):
        """Проверка ошибки при отсутствии обязательного поля."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(MISSING_REQUIRED_FIELD_YAML)
            f.flush()
            temp_path = f.name

        try:
            with pytest.raises(ValidationError) as exc_info:
                load_manifest(temp_path)
            
            # Проверяем, что ошибка указывает на отсутствующее поле
            error_str = str(exc_info.value)
            assert "sensor" in error_str.lower() or "missing" in error_str.lower() or "field required" in error_str.lower()
            
        finally:
            Path(temp_path).unlink()

    def test_file_not_found(self):
        """Проверка ошибки при отсутствии файла."""
        with pytest.raises(FileNotFoundError):
            load_manifest("/nonexistent/path/manifest.yaml")

    def test_invalid_yaml_syntax(self):
        """Проверка ошибки при некорректном YAML синтаксисе."""
        invalid_yaml = """
version: 1
instance:
  id: test
  name: Test
  owner: Owner
  created_at: '2024-01-01'
devices:
  - id: light.kitchen
    name: Test
    room: kitchen
    motion_sensor: sensor.motion
    motion_timeout_sec: [invalid_list_here
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(invalid_yaml)
            f.flush()
            temp_path = f.name

        try:
            with pytest.raises(yaml.YAMLError):
                load_manifest(temp_path)
        finally:
            Path(temp_path).unlink()


class TestFlatDeviceList:
    """Тесты плоской структуры устройств."""

    def test_devices_are_flat_list(self):
        """Проверка что devices это плоский список, а не словарь."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(VALID_MANIFEST_YAML)
            f.flush()
            temp_path = f.name

        try:
            manifest = load_manifest(temp_path)
            
            # devices должен быть списком
            assert isinstance(manifest.devices, list)
            
            # Все элементы должны быть устройствами с полем type
            for device in manifest.devices:
                assert hasattr(device, 'type')
                assert hasattr(device, 'id')
                assert hasattr(device, 'name')
                assert hasattr(device, 'room')
                
        finally:
            Path(temp_path).unlink()
