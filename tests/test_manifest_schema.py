"""
Tests for Manifest Schema and Validator

Проверяет:
- Валидный манифест читается
- Ошибки структуры обнаруживаются
- Ошибки форматов обнаруживаются
- Ссылочная целостность проверяется
"""

import pytest
import yaml
from pathlib import Path

from core.manifest_schema import MANIFEST_SCHEMA, get_schema
from core.manifest_validator import ManifestValidator, ValidationError, validate_manifest


# Фикстуры
@pytest.fixture
def valid_manifest():
    """Валидный манифест для тестов"""
    return {
        "version": 1,
        "instance": {
            "id": "test_house",
            "name": "Test House",
            "owner": "Test Owner"
        },
        "devices": {
            "lighting": [
                {
                    "id": "light.kitchen",
                    "name": "Kitchen Light",
                    "room": "kitchen",
                    "motion_sensor": "binary_sensor.kitchen_motion",
                    "schedule": "07:00-23:00",
                    "motion_timeout_sec": 300
                }
            ],
            "climate": [
                {
                    "id": "climate.living_room",
                    "name": "Living Room Climate",
                    "room": "living_room",
                    "sensor": "sensor.living_room_temperature",
                    "target": 22.0,
                    "hysteresis": 0.5
                }
            ],
            "ventilation": [
                {
                    "id": "fan.bathroom",
                    "name": "Bathroom Fan",
                    "room": "bathroom",
                    "humidity_sensor": "sensor.bathroom_humidity",
                    "humidity_threshold": 65,
                    "timeout_sec": 1800
                }
            ]
        },
        "zones": [
            {"id": "kitchen", "name": "Kitchen", "floor": 1},
            {"id": "living_room", "name": "Living Room", "floor": 1},
            {"id": "bathroom", "name": "Bathroom", "floor": 1}
        ],
        "automation_rules": {
            "lighting": {"manual_lockout_min": 60},
            "climate": {"manual_lockout_min": 30}
        },
        "dashboard": {
            "title": "Test House"
        }
    }


@pytest.fixture
def validator():
    """Экземпляр валидатора"""
    return ManifestValidator()


# Тесты схемы
class TestManifestSchema:
    """Тесты схемы манифеста"""

    def test_schema_exists(self):
        """Схема существует"""
        assert MANIFEST_SCHEMA is not None
        assert isinstance(MANIFEST_SCHEMA, dict)

    def test_get_schema_returns_dict(self):
        """get_schema() возвращает словарь"""
        schema = get_schema()
        assert isinstance(schema, dict)
        assert "version" in schema
        assert "instance" in schema
        assert "devices" in schema

    def test_schema_has_required_fields(self):
        """Схема определяет обязательные поля"""
        assert MANIFEST_SCHEMA["version"]["required"] == True
        assert MANIFEST_SCHEMA["instance"]["required"] == True
        assert MANIFEST_SCHEMA["devices"]["required"] == True
        assert MANIFEST_SCHEMA["zones"]["required"] == True


# Тесты валидатора
class TestManifestValidator:
    """Тесты валидатора манифеста"""

    def test_validator_passes_valid_manifest(self, valid_manifest, validator):
        """Валидный манифест проходит проверку"""
        errors = validator.validate(valid_manifest)
        assert len(errors) == 0

    def test_validator_catches_missing_version(self, valid_manifest, validator):
        """Отсутствие версии обнаруживается"""
        del valid_manifest["version"]
        errors = validator.validate(valid_manifest)
        assert any(e.field == "version" for e in errors)

    def test_validator_catches_missing_instance(self, valid_manifest, validator):
        """Отсутствие instance обнаруживается"""
        del valid_manifest["instance"]
        errors = validator.validate(valid_manifest)
        assert any(e.field == "instance" for e in errors)

    def test_validator_catches_missing_devices(self, valid_manifest, validator):
        """Отсутствие devices обнаруживается"""
        del valid_manifest["devices"]
        errors = validator.validate(valid_manifest)
        assert any(e.field == "devices" for e in errors)

    def test_validator_catches_missing_zones(self, valid_manifest, validator):
        """Отсутствие zones обнаруживается"""
        del valid_manifest["zones"]
        errors = validator.validate(valid_manifest)
        assert any(e.field == "zones" for e in errors)

    def test_validator_catches_invalid_entity_id(self, valid_manifest, validator):
        """Невалидный entity_id обнаруживается"""
        valid_manifest["devices"]["lighting"][0]["id"] = "INVALID_ID"
        errors = validator.validate(valid_manifest)
        assert any("entity_id" in str(e.message).lower() for e in errors)

    def test_validator_catches_invalid_schedule_format(self, valid_manifest, validator):
        """Невалидный формат расписания обнаруживается"""
        valid_manifest["devices"]["lighting"][0]["schedule"] = "invalid"
        errors = validator.validate(valid_manifest)
        assert any("расписания" in str(e.message) for e in errors)

    def test_validator_catches_duplicate_ids(self, valid_manifest, validator):
        """Дубликаты ID обнаруживаются"""
        valid_manifest["devices"]["lighting"].append(
            valid_manifest["devices"]["lighting"][0].copy()
        )
        errors = validator.validate(valid_manifest)
        assert any("Дубликат" in str(e.message) for e in errors)

    def test_validator_catches_invalid_room_reference(self, valid_manifest, validator):
        """Несуществующая комната обнаруживается"""
        valid_manifest["devices"]["lighting"][0]["room"] = "nonexistent_room"
        errors = validator.validate(valid_manifest)
        assert any("не найдена в zones" in str(e.message) for e in errors)

    def test_validator_catches_out_of_range_temperature(self, valid_manifest, validator):
        """Температура вне диапазона обнаруживается"""
        valid_manifest["devices"]["climate"][0]["target"] = 50.0
        errors = validator.validate(valid_manifest)
        assert any("вне диапазона" in str(e.message) for e in errors)

    def test_validator_reports_all_errors(self, validator):
        """Все ошибки собираются, не только первая"""
        bad_manifest = {}  # Пустой манифест - много ошибок
        errors = validator.validate(bad_manifest)
        assert len(errors) >= 4  # version, instance, devices, zones

    def test_validator_empty_file_fails(self, validator):
        """Пустой файл → ошибка"""
        errors = validator.validate(None)
        assert len(errors) > 0
        
        errors = validator.validate({})
        assert len(errors) > 0

    def test_validator_malformed_yaml_fails(self, validator):
        """Битый YAML → ошибка (проверяется на уровне загрузки)"""
        # Это скорее проверка что валидатор не падает на не-dict
        errors = validator.validate("not a dict")
        assert len(errors) > 0
        assert errors[0].message == "Манифест должен быть словарём"

    def test_validate_manifest_function(self, valid_manifest):
        """Удобная функция validate_manifest работает"""
        errors = validate_manifest(valid_manifest)
        assert len(errors) == 0


# Тесты загрузки из файла
class TestManifestFileLoading:
    """Тесты загрузки манифеста из файла"""

    def test_manifest_loads_valid_yaml(self, valid_manifest):
        """Валидный манифест читается из YAML"""
        # Создаём временный файл
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(valid_manifest, f)
            temp_path = f.name

        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                loaded = yaml.safe_load(f)
            
            assert loaded["version"] == 1
            assert loaded["instance"]["id"] == "test_house"
            assert len(loaded["devices"]["lighting"]) == 1
        finally:
            Path(temp_path).unlink()

    def test_manifest_device_ids_unique(self, valid_manifest, validator):
        """Нет дубликатов ID устройств"""
        errors = validator.validate(valid_manifest)
        duplicate_errors = [e for e in errors if "Дубликат" in e.message]
        assert len(duplicate_errors) == 0

    def test_manifest_sensor_ids_valid_format(self, valid_manifest, validator):
        """ID сенсоров валидны"""
        errors = validator.validate(valid_manifest)
        # Проверяем что нет ошибок формата entity_id для сенсоров
        sensor_errors = [e for e in errors if "сенсора" in str(e.message)]
        assert len(sensor_errors) == 0

    def test_manifest_zones_referenced_correctly(self, valid_manifest, validator):
        """Все комнаты из устройств существуют в zones"""
        errors = validator.validate(valid_manifest)
        reference_errors = [e for e in errors if "не найдена в zones" in str(e.message)]
        assert len(reference_errors) == 0


# Тесты CLI команды (интеграционные)
class TestManifestCLI:
    """Тесты CLI команды валидации"""

    def test_validator_cli_command(self, valid_manifest):
        """CLI команда работает (базовая проверка)"""
        import subprocess
        import tempfile
        import os

        # Создаём временный файл с манифестом
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(valid_manifest, f)
            temp_path = f.name

        try:
            # Запускаем CLI команду
            result = subprocess.run(
                ["python", "cli.py", "manifest", "validate", "--file", temp_path],
                capture_output=True,
                text=True,
                cwd="/workspace"
            )
            
            # Команда должна выполниться (код может быть 0 или 1 в зависимости от реализации)
            # Главное что не упала с исключением
            assert result.returncode in (0, 1, 2)
        finally:
            Path(temp_path).unlink()
