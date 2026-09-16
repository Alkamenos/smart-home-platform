"""
Tests for Manifest Schema - Тесты схемы манифеста платформы умного дома

Проверка спецификации схемы:
1. Структура схемы MANIFEST_SCHEMA
2. Функция get_schema() возвращает корректную схему
3. Проверка всех обязательных полей схемы
"""

import pytest
from src.core.manifest_schema import MANIFEST_SCHEMA, get_schema


class TestManifestSchemaStructure:
    """Тесты структуры схемы манифеста"""

    def test_schema_is_dict(self):
        """Спецификация: Схема должна быть словарём"""
        assert isinstance(MANIFEST_SCHEMA, dict)

    def test_schema_has_version_field(self):
        """Спецификация: Схема должна содержать поле version"""
        assert "version" in MANIFEST_SCHEMA
        assert MANIFEST_SCHEMA["version"]["required"] is True
        assert MANIFEST_SCHEMA["version"]["type"] == "integer"

    def test_schema_has_instance_field(self):
        """Спецификация: Схема должна содержать поле instance"""
        assert "instance" in MANIFEST_SCHEMA
        assert MANIFEST_SCHEMA["instance"]["required"] is True
        assert MANIFEST_SCHEMA["instance"]["type"] == "dict"

    def test_instance_schema_has_required_fields(self):
        """Спецификация: instance должен иметь обязательные поля id и name"""
        instance_schema = MANIFEST_SCHEMA["instance"]["schema"]
        assert "id" in instance_schema
        assert instance_schema["id"]["required"] is True
        assert instance_schema["id"]["type"] == "string"
        
        assert "name" in instance_schema
        assert instance_schema["name"]["required"] is True
        assert instance_schema["name"]["type"] == "string"

    def test_instance_has_optional_fields(self):
        """Спецификация: instance может иметь опциональные поля owner и created_at"""
        instance_schema = MANIFEST_SCHEMA["instance"]["schema"]
        assert "owner" in instance_schema
        # required может отсутствовать для опциональных полей
        assert instance_schema["owner"].get("required") is not True
        assert instance_schema["owner"]["type"] == "string"
        
        assert "created_at" in instance_schema
        assert instance_schema["created_at"].get("required") is not True
        assert instance_schema["created_at"]["type"] == "string"

    def test_schema_has_devices_field(self):
        """Спецификация: Схема должна содержать поле devices"""
        assert "devices" in MANIFEST_SCHEMA
        assert MANIFEST_SCHEMA["devices"]["required"] is True
        assert MANIFEST_SCHEMA["devices"]["type"] == "dict"

    def test_devices_has_lighting_section(self):
        """Спецификация: devices должен содержать секцию lighting"""
        devices_schema = MANIFEST_SCHEMA["devices"]["schema"]
        assert "lighting" in devices_schema
        lighting = devices_schema["lighting"]
        assert lighting["type"] == "list"
        assert lighting["required"] is True

    def test_lighting_device_schema(self):
        """Спецификация: lighting устройство должно иметь правильную схему"""
        lighting_schema = MANIFEST_SCHEMA["devices"]["schema"]["lighting"]["schema"]
        assert isinstance(lighting_schema, dict)
        assert lighting_schema["type"] == "dict"
        
        device_fields = lighting_schema["schema"]
        # Обязательные поля
        assert "id" in device_fields
        assert device_fields["id"]["required"] is True
        assert device_fields["id"]["type"] == "string"
        
        assert "name" in device_fields
        assert device_fields["name"]["required"] is True
        assert device_fields["name"]["type"] == "string"
        
        assert "room" in device_fields
        assert device_fields["room"]["required"] is True
        assert device_fields["room"]["type"] == "string"
        
        # Опциональные поля
        assert "motion_sensor" in device_fields
        assert device_fields["motion_sensor"]["type"] == "string"
        
        assert "schedule" in device_fields
        assert device_fields["schedule"]["type"] == "string"
        
        assert "motion_timeout_sec" in device_fields
        assert device_fields["motion_timeout_sec"]["type"] == "integer"

    def test_devices_has_climate_section(self):
        """Спецификация: devices должен содержать секцию climate"""
        devices_schema = MANIFEST_SCHEMA["devices"]["schema"]
        assert "climate" in devices_schema
        climate = devices_schema["climate"]
        assert climate["type"] == "list"
        # climate не обязателен (не указан required=True)

    def test_climate_device_schema(self):
        """Спецификация: climate устройство должно иметь правильную схему"""
        climate_schema = MANIFEST_SCHEMA["devices"]["schema"]["climate"]["schema"]
        assert isinstance(climate_schema, dict)
        assert climate_schema["type"] == "dict"
        
        device_fields = climate_schema["schema"]
        # Обязательные поля
        assert "id" in device_fields
        assert device_fields["id"]["required"] is True
        assert device_fields["id"]["type"] == "string"
        
        assert "name" in device_fields
        assert device_fields["name"]["required"] is True
        assert device_fields["name"]["type"] == "string"
        
        assert "room" in device_fields
        assert device_fields["room"]["required"] is True
        assert device_fields["room"]["type"] == "string"
        
        assert "sensor" in device_fields
        assert device_fields["sensor"]["required"] is True
        assert device_fields["sensor"]["type"] == "string"
        
        # Опциональные поля
        assert "target" in device_fields
        assert device_fields["target"]["type"] == "float"
        
        assert "hysteresis" in device_fields
        assert device_fields["hysteresis"]["type"] == "float"
        
        assert "modes" in device_fields
        assert device_fields["modes"]["type"] == "list"

    def test_devices_has_ventilation_section(self):
        """Спецификация: devices должен содержать секцию ventilation"""
        devices_schema = MANIFEST_SCHEMA["devices"]["schema"]
        assert "ventilation" in devices_schema
        ventilation = devices_schema["ventilation"]
        assert ventilation["type"] == "list"
        # ventilation не обязателен (не указан required=True)

    def test_ventilation_device_schema(self):
        """Спецификация: ventilation устройство должно иметь правильную схему"""
        vent_schema = MANIFEST_SCHEMA["devices"]["schema"]["ventilation"]["schema"]
        assert isinstance(vent_schema, dict)
        assert vent_schema["type"] == "dict"
        
        device_fields = vent_schema["schema"]
        # Обязательные поля
        assert "id" in device_fields
        assert device_fields["id"]["required"] is True
        assert device_fields["id"]["type"] == "string"
        
        assert "name" in device_fields
        assert device_fields["name"]["required"] is True
        assert device_fields["name"]["type"] == "string"
        
        assert "room" in device_fields
        assert device_fields["room"]["required"] is True
        assert device_fields["room"]["type"] == "string"
        
        # Опциональные поля
        assert "humidity_sensor" in device_fields
        assert device_fields["humidity_sensor"]["type"] == "string"
        
        assert "humidity_threshold" in device_fields
        assert device_fields["humidity_threshold"]["type"] == "float"
        
        assert "timeout_sec" in device_fields
        assert device_fields["timeout_sec"]["type"] == "integer"

    def test_schema_has_automation_rules_section(self):
        """Спецификация: Схема должна содержать секцию automation_rules"""
        assert "automation_rules" in MANIFEST_SCHEMA
        rules = MANIFEST_SCHEMA["automation_rules"]
        assert rules["type"] == "dict"
        # automation_rules не обязателен (не указан required=True)
        
        rules_schema = rules["schema"]
        assert "lighting" in rules_schema
        assert "climate" in rules_schema
        assert "ventilation" in rules_schema

    def test_schema_has_zones_field(self):
        """Спецификация: Схема должна содержать поле zones"""
        assert "zones" in MANIFEST_SCHEMA
        assert MANIFEST_SCHEMA["zones"]["required"] is True
        assert MANIFEST_SCHEMA["zones"]["type"] == "list"

    def test_zone_schema(self):
        """Спецификация: Зона должна иметь правильную схему"""
        zone_schema = MANIFEST_SCHEMA["zones"]["schema"]
        assert isinstance(zone_schema, dict)
        assert zone_schema["type"] == "dict"
        
        zone_fields = zone_schema["schema"]
        # Обязательные поля
        assert "id" in zone_fields
        assert zone_fields["id"]["required"] is True
        assert zone_fields["id"]["type"] == "string"
        
        assert "name" in zone_fields
        assert zone_fields["name"]["required"] is True
        assert zone_fields["name"]["type"] == "string"
        
        # Опциональные поля
        assert "floor" in zone_fields
        assert zone_fields["floor"]["type"] == "integer"

    def test_schema_has_dashboard_section(self):
        """Спецификация: Схема должна содержать секцию dashboard"""
        assert "dashboard" in MANIFEST_SCHEMA
        dashboard = MANIFEST_SCHEMA["dashboard"]
        assert dashboard["type"] == "dict"
        # dashboard не обязателен (не указан required=True)

    def test_dashboard_schema_fields(self):
        """Спецификация: dashboard должен иметь правильные поля"""
        dashboard_schema = MANIFEST_SCHEMA["dashboard"]["schema"]
        assert isinstance(dashboard_schema, dict)
        
        # Все поля dashboard опциональны
        assert "title" in dashboard_schema
        assert dashboard_schema["title"]["type"] == "string"
        
        assert "show_motion_sensors" in dashboard_schema
        assert dashboard_schema["show_motion_sensors"]["type"] == "boolean"
        
        assert "show_climate" in dashboard_schema
        assert dashboard_schema["show_climate"]["type"] == "boolean"
        
        assert "show_history" in dashboard_schema
        assert dashboard_schema["show_history"]["type"] == "boolean"
        
        assert "history_days" in dashboard_schema
        assert dashboard_schema["history_days"]["type"] == "integer"


class TestGetSchemaFunction:
    """Тесты функции get_schema()"""

    def test_get_schema_returns_dict(self):
        """Спецификация: get_schema() должен возвращать словарь"""
        schema = get_schema()
        assert isinstance(schema, dict)

    def test_get_schema_returns_same_schema(self):
        """Спецификация: get_schema() должен возвращать ту же схему что и MANIFEST_SCHEMA"""
        schema = get_schema()
        assert schema == MANIFEST_SCHEMA

    def test_get_schema_multiple_calls_consistent(self):
        """Спецификация: Множественные вызовы get_schema() должны возвращать одинаковый результат"""
        schema1 = get_schema()
        schema2 = get_schema()
        assert schema1 == schema2
        assert schema1 is schema2  # Должен возвращать тот же объект


class TestManifestSchemaCompleteness:
    """Тесты полноты схемы манифеста"""

    def test_all_required_top_level_fields_present(self):
        """Спецификация: Все обязательные поля верхнего уровня присутствуют"""
        required_fields = ["version", "instance", "devices", "zones"]
        for field in required_fields:
            assert field in MANIFEST_SCHEMA
            assert MANIFEST_SCHEMA[field].get("required") is True

    def test_no_extra_top_level_fields_marked_required(self):
        """Спецификация: Нет лишних обязательных полей верхнего уровня"""
        optional_fields = ["automation_rules", "dashboard"]
        for field in optional_fields:
            if field in MANIFEST_SCHEMA:
                # Если поле есть, оно не должно быть обязательным
                assert MANIFEST_SCHEMA[field].get("required") is not True

    def test_schema_type_definitions_valid(self):
        """Спецификация: Все типы данных в схеме корректны"""
        valid_types = {"integer", "string", "float", "boolean", "dict", "list"}
        
        def check_types(schema_part, path=""):
            if isinstance(schema_part, dict):
                if "type" in schema_part:
                    field_type = schema_part["type"]
                    assert field_type in valid_types, f"Невалидный тип {field_type} в {path}"
                if "schema" in schema_part:
                    check_types(schema_part["schema"], f"{path}.schema")
                for key, value in schema_part.items():
                    if key not in ["type", "required", "schema"]:
                        check_types(value, f"{path}.{key}")
            elif isinstance(schema_part, list):
                for item in schema_part:
                    check_types(item, path)
        
        check_types(MANIFEST_SCHEMA)
