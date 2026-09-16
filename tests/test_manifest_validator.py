"""
Tests for Manifest Validator - Тесты валидатора манифеста платформы умного дома

Проверка спецификации валидации:
1. Структурные проверки (обязательные поля)
2. Проверка типов данных
3. Проверка форматов (entity_id, расписания)
4. Ссылочная целостность
5. Логические ограничения (диапазоны значений, уникальность)
"""

import pytest
from src.core.manifest_validator import ManifestValidator, ValidationError, validate_manifest


class TestManifestValidatorStructure:
    """Тесты структурной валидации манифеста"""

    @pytest.fixture
    def validator(self):
        return ManifestValidator()

    def test_valid_minimal_manifest(self, validator):
        """Спецификация: Минимальный валидный манифест должен проходить валидацию"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert len(errors) == 0

    def test_missing_version(self, validator):
        """Спецификация: Отсутствие поля version должно вызывать ошибку"""
        manifest = {
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "version" for e in errors)

    def test_missing_instance(self, validator):
        """Спецификация: Отсутствие секции instance должно вызывать ошибку"""
        manifest = {
            "version": 1,
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "instance" for e in errors)

    def test_missing_instance_id(self, validator):
        """Спецификация: Отсутствие instance.id должно вызывать ошибку"""
        manifest = {
            "version": 1,
            "instance": {"name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "instance.id" for e in errors)

    def test_missing_instance_name(self, validator):
        """Спецификация: Отсутствие instance.name должно вызывать ошибку"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "instance.name" for e in errors)

    def test_missing_devices(self, validator):
        """Спецификация: Отсутствие секции devices должно вызывать ошибку"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "devices" for e in errors)

    def test_missing_zones(self, validator):
        """Спецификация: Отсутствие секции zones должно вызывать ошибку"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
        }
        errors = validator.validate(manifest)
        assert any(e.field == "zones" for e in errors)

    def test_manifest_not_dict(self, validator):
        """Спецификация: Манифест должен быть словарём"""
        errors = validator.validate("not a dict")
        assert len(errors) == 1
        assert "Манифест должен быть словарём" in errors[0].message

    def test_multiple_structural_errors(self, validator):
        """Спецификация: Должны собираться все структурные ошибки"""
        manifest = {"version": "invalid"}
        errors = validator.validate(manifest)
        error_fields = [e.field for e in errors]
        assert "instance" in error_fields
        assert "devices" in error_fields
        assert "zones" in error_fields


class TestManifestValidatorTypes:
    """Тесты проверки типов данных"""

    @pytest.fixture
    def validator(self):
        return ManifestValidator()

    def test_version_must_be_integer(self, validator):
        """Спецификация: version должно быть целым числом"""
        manifest = {
            "version": "1.0",
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "version" and "целым числом" in e.message for e in errors)

    def test_version_float_invalid(self, validator):
        """Спецификация: version как float должно вызывать ошибку"""
        manifest = {
            "version": 1.5,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "version" for e in errors)

    def test_instance_must_be_dict(self, validator):
        """Спецификация: instance должен быть словарём"""
        manifest = {
            "version": 1,
            "instance": "not a dict",
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "instance" and "словарём" in e.message for e in errors)

    def test_devices_must_be_dict(self, validator):
        """Спецификация: devices должен быть словарём"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": "not a dict",
            "zones": [],
        }
        errors = validator.validate(manifest)
        assert any(e.field == "devices" and "словарём" in e.message for e in errors)

    def test_zones_must_be_list(self, validator):
        """Спецификация: zones должен быть списком"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": "not a list",
        }
        errors = validator.validate(manifest)
        assert any(e.field == "zones" and "списком" in e.message for e in errors)


class TestManifestValidatorFormats:
    """Тесты проверки форматов строк"""

    @pytest.fixture
    def validator(self):
        return ManifestValidator()

    def test_valid_entity_id(self, validator):
        """Спецификация: Валидный entity_id формата domain.entity_name"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "living_room",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        assert len(errors) == 0

    def test_invalid_entity_id_no_dot(self, validator):
        """Спецификация: entity_id без точки должен быть невалидным"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "invalid_id",
                        "name": "Bad Light",
                        "room": "living_room",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный entity_id" in e.message for e in errors)

    def test_invalid_entity_id_uppercase(self, validator):
        """Спецификация: entity_id с заглавными буквами должен быть невалидным"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "Light.LivingRoom",
                        "name": "Bad Light",
                        "room": "living_room",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный entity_id" in e.message for e in errors)

    def test_valid_schedule_format(self, validator):
        """Спецификация: Валидное расписание формата HH:MM-HH:MM"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "living_room",
                        "schedule": "07:00-23:00",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        schedule_errors = [e for e in errors if "schedule" in e.field]
        assert len(schedule_errors) == 0

    def test_invalid_schedule_format(self, validator):
        """Спецификация: Невалидное расписание должно вызывать ошибку"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "living_room",
                        "schedule": "7:00-23:00",  # Неправильный формат
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный формат расписания" in e.message for e in errors)

    def test_invalid_motion_sensor_entity_id(self, validator):
        """Спецификация: motion_sensor должен быть валидным entity_id"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "living_room",
                        "motion_sensor": "invalid_sensor",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный entity_id сенсора" in e.message for e in errors)

    def test_climate_device_invalid_entity_id(self, validator):
        """Спецификация: climate устройство должно иметь валидный entity_id"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "invalid_climate",
                        "name": "AC",
                        "room": "bedroom",
                        "sensor": "sensor.bedroom_temp",
                    }
                ]
            },
            "zones": [{"id": "bedroom", "name": "Bedroom"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный entity_id" in e.message for e in errors)

    def test_climate_device_invalid_sensor_entity_id(self, validator):
        """Спецификация: sensor climate устройства должен быть валидным entity_id"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.bedroom",
                        "name": "AC",
                        "room": "bedroom",
                        "sensor": "invalid_sensor",
                    }
                ]
            },
            "zones": [{"id": "bedroom", "name": "Bedroom"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный entity_id сенсора" in e.message for e in errors)

    def test_ventilation_device_invalid_entity_id(self, validator):
        """Спецификация: ventilation устройство должно иметь валидный entity_id"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "ventilation": [
                    {
                        "id": "invalid_vent",
                        "name": "Ventilator",
                        "room": "bathroom",
                    }
                ]
            },
            "zones": [{"id": "bathroom", "name": "Bathroom"}],
        }
        errors = validator.validate(manifest)
        assert any("Невалидный entity_id" in e.message for e in errors)


class TestManifestValidatorReferences:
    """Тесты ссылочной целостности"""

    @pytest.fixture
    def validator(self):
        return ManifestValidator()

    def test_valid_room_reference(self, validator):
        """Спецификация: Устройство должно ссылаться на существующую комнату"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "living_room",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        room_errors = [e for e in errors if "room" in e.field]
        assert len(room_errors) == 0

    def test_invalid_room_reference(self, validator):
        """Спецификация: Устройство не должно ссылаться на несуществующую комнату"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "nonexistent_room",
                    }
                ]
            },
            "zones": [{"id": "living_room", "name": "Living Room"}],
        }
        errors = validator.validate(manifest)
        assert any("не найдена в zones" in e.message for e in errors)

    def test_climate_invalid_room_reference(self, validator):
        """Спецификация: Climate устройство должно ссылаться на существующую комнату"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.bedroom",
                        "name": "AC",
                        "room": "missing_room",
                        "sensor": "sensor.temp",
                    }
                ]
            },
            "zones": [{"id": "bedroom", "name": "Bedroom"}],
        }
        errors = validator.validate(manifest)
        assert any("не найдена в zones" in e.message for e in errors)

    def test_ventilation_invalid_room_reference(self, validator):
        """Спецификация: Ventilation устройство должно ссылаться на существующую комнату"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "ventilation": [
                    {
                        "id": "vent.bathroom",
                        "name": "Fan",
                        "room": "unknown_room",
                    }
                ]
            },
            "zones": [{"id": "bathroom", "name": "Bathroom"}],
        }
        errors = validator.validate(manifest)
        assert any("не найдена в zones" in e.message for e in errors)


class TestManifestValidatorLogic:
    """Тесты логических ограничений"""

    @pytest.fixture
    def validator(self):
        return ManifestValidator()

    def test_duplicate_device_id_same_type(self, validator):
        """Спецификация: ID устройств одного типа должны быть уникальны"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "lighting": [
                    {"id": "light.same", "name": "Light 1", "room": "room1"},
                    {"id": "light.same", "name": "Light 2", "room": "room2"},
                ]
            },
            "zones": [
                {"id": "room1", "name": "Room 1"},
                {"id": "room2", "name": "Room 2"},
            ],
        }
        errors = validator.validate(manifest)
        assert any("Дубликат ID" in e.message for e in errors)

    def test_duplicate_zone_id(self, validator):
        """Спецификация: ID зон должны быть уникальны"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [
                {"id": "duplicate", "name": "Zone 1"},
                {"id": "duplicate", "name": "Zone 2"},
            ],
        }
        errors = validator.validate(manifest)
        assert any("Дубликат ID зоны" in e.message for e in errors)

    def test_temperature_target_below_range(self, validator):
        """Спецификация: Целевая температура должна быть в диапазоне 10-35"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.room",
                        "name": "AC",
                        "room": "room",
                        "sensor": "sensor.temp",
                        "target": 5.0,  # Ниже минимума
                    }
                ]
            },
            "zones": [{"id": "room", "name": "Room"}],
        }
        errors = validator.validate(manifest)
        assert any("вне диапазона 10-35" in e.message for e in errors)

    def test_temperature_target_above_range(self, validator):
        """Спецификация: Целевая температура должна быть в диапазоне 10-35"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.room",
                        "name": "AC",
                        "room": "room",
                        "sensor": "sensor.temp",
                        "target": 40.0,  # Выше максимума
                    }
                ]
            },
            "zones": [{"id": "room", "name": "Room"}],
        }
        errors = validator.validate(manifest)
        assert any("вне диапазона 10-35" in e.message for e in errors)

    def test_temperature_target_at_boundary(self, validator):
        """Спецификация: Температура на границе диапазона должна быть валидной"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.room",
                        "name": "AC",
                        "room": "room",
                        "sensor": "sensor.temp",
                        "target": 10.0,  # На нижней границе
                    }
                ]
            },
            "zones": [{"id": "room", "name": "Room"}],
        }
        errors = validator.validate(manifest)
        temp_errors = [e for e in errors if "target" in e.field and "температура" in e.message]
        assert len(temp_errors) == 0

    def test_hysteresis_below_range(self, validator):
        """Спецификация: Гистерезис должен быть в диапазоне 0.1-5.0"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.room",
                        "name": "AC",
                        "room": "room",
                        "sensor": "sensor.temp",
                        "hysteresis": 0.05,  # Ниже минимума
                    }
                ]
            },
            "zones": [{"id": "room", "name": "Room"}],
        }
        errors = validator.validate(manifest)
        assert any("Гистерезис" in e.message and "вне диапазона 0.1-5.0" in e.message for e in errors)

    def test_hysteresis_above_range(self, validator):
        """Спецификация: Гистерезис должен быть в диапазоне 0.1-5.0"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "climate": [
                    {
                        "id": "climate.room",
                        "name": "AC",
                        "room": "room",
                        "sensor": "sensor.temp",
                        "hysteresis": 6.0,  # Выше максимума
                    }
                ]
            },
            "zones": [{"id": "room", "name": "Room"}],
        }
        errors = validator.validate(manifest)
        assert any("Гистерезис" in e.message and "вне диапазона 0.1-5.0" in e.message for e in errors)

    def test_humidity_threshold_negative(self, validator):
        """Спецификация: Порог влажности должен быть в диапазоне 0-100"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "ventilation": [
                    {
                        "id": "vent.bathroom",
                        "name": "Fan",
                        "room": "bathroom",
                        "humidity_threshold": -10,  # Отрицательное значение
                    }
                ]
            },
            "zones": [{"id": "bathroom", "name": "Bathroom"}],
        }
        errors = validator.validate(manifest)
        assert any("Порог влажности" in e.message and "вне диапазона 0-100" in e.message for e in errors)

    def test_humidity_threshold_above_100(self, validator):
        """Спецификация: Порог влажности должен быть в диапазоне 0-100"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "ventilation": [
                    {
                        "id": "vent.bathroom",
                        "name": "Fan",
                        "room": "bathroom",
                        "humidity_threshold": 150,  # Выше 100%
                    }
                ]
            },
            "zones": [{"id": "bathroom", "name": "Bathroom"}],
        }
        errors = validator.validate(manifest)
        assert any("Порог влажности" in e.message and "вне диапазона 0-100" in e.message for e in errors)

    def test_humidity_threshold_at_boundary(self, validator):
        """Спецификация: Порог влажности на границе должен быть валидным"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {
                "ventilation": [
                    {
                        "id": "vent.bathroom",
                        "name": "Fan",
                        "room": "bathroom",
                        "humidity_threshold": 0,  # На нижней границе
                    }
                ]
            },
            "zones": [{"id": "bathroom", "name": "Bathroom"}],
        }
        errors = validator.validate(manifest)
        humidity_errors = [e for e in errors if "Порог влажности" in e.message]
        assert len(humidity_errors) == 0


class TestValidationErrorClass:
    """Тесты класса ValidationError"""

    def test_error_string_representation(self):
        """Спецификация: ValidationError должен иметь строковое представление"""
        error = ValidationError(field="test.field", message="Test error message")
        assert str(error) == "test.field: Test error message"

    def test_error_default_severity(self):
        """Спецификация: По умолчанию severity должен быть 'error'"""
        error = ValidationError(field="test.field", message="Test error")
        assert error.severity == "error"

    def test_error_custom_severity(self):
        """Спецификация: Можно установить custom severity"""
        error = ValidationError(field="test.field", message="Warning", severity="warning")
        assert error.severity == "warning"


class TestValidateManifestFunction:
    """Тесты удобной функции validate_manifest"""

    def test_validate_manifest_function(self):
        """Спецификация: Функция validate_manifest должна работать как метод класса"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Test Home"},
            "devices": {"lighting": []},
            "zones": [],
        }
        errors = validate_manifest(manifest)
        assert isinstance(errors, list)
        assert len(errors) == 0

    def test_validate_manifest_function_with_errors(self):
        """Спецификация: Функция должна возвращать ошибки при невалидном манифесте"""
        manifest = {"version": "invalid"}
        errors = validate_manifest(manifest)
        assert len(errors) > 0


class TestManifestValidatorComprehensive:
    """Комплексные тесты валидации манифеста"""

    @pytest.fixture
    def validator(self):
        return ManifestValidator()

    def test_fully_valid_manifest(self, validator):
        """Спецификация: Полностью валидный манифест со всеми устройствами"""
        manifest = {
            "version": 1,
            "instance": {"id": "home_001", "name": "Smart Home", "owner": "John", "created_at": "2024-01-01"},
            "devices": {
                "lighting": [
                    {
                        "id": "light.living_room",
                        "name": "Living Room Light",
                        "room": "living_room",
                        "motion_sensor": "sensor.living_room_motion",
                        "schedule": "07:00-23:00",
                        "motion_timeout_sec": 60,
                    }
                ],
                "climate": [
                    {
                        "id": "climate.bedroom",
                        "name": "Bedroom AC",
                        "room": "bedroom",
                        "sensor": "sensor.bedroom_temp",
                        "target": 22.5,
                        "hysteresis": 0.5,
                        "modes": ["cool", "heat"],
                    }
                ],
                "ventilation": [
                    {
                        "id": "vent.bathroom",
                        "name": "Bathroom Fan",
                        "room": "bathroom",
                        "humidity_sensor": "sensor.bathroom_humidity",
                        "humidity_threshold": 70.0,
                        "timeout_sec": 300,
                    }
                ],
            },
            "zones": [
                {"id": "living_room", "name": "Living Room", "floor": 1},
                {"id": "bedroom", "name": "Bedroom", "floor": 2},
                {"id": "bathroom", "name": "Bathroom", "floor": 2},
            ],
            "automation_rules": {
                "lighting": {},
                "climate": {},
                "ventilation": {},
            },
            "dashboard": {
                "title": "My Smart Home",
                "show_motion_sensors": True,
                "show_climate": True,
                "show_history": True,
                "history_days": 7,
            },
        }
        errors = validator.validate(manifest)
        assert len(errors) == 0

    def test_multiple_errors_accumulated(self, validator):
        """Спецификация: Все ошибки должны быть собраны в одном списке"""
        manifest = {
            "version": "invalid",
            "instance": {"id": "bad-id"},  # missing name
            "devices": {"lighting": [{"id": "bad", "name": "Bad", "room": "missing"}]},
            "zones": [{"id": "dup", "name": "Dup"}, {"id": "dup", "name": "Dup2"}],
        }
        errors = validator.validate(manifest)
        # Ожидаем множественные ошибки разных типов
        error_fields = [e.field for e in errors]
        assert "version" in error_fields
        assert "instance.name" in error_fields
        assert any("Невалидный entity_id" in e.message for e in errors)
        assert any("не найдена в zones" in e.message for e in errors)
        assert any("Дубликат ID зоны" in e.message for e in errors)
