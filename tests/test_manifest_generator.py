"""
Tests for Manifest Generator

Проверяет:
- Генерация автоматов освещения
- Генерация маппингов
- Генерация климатических автоматов
- Учёт параметров из манифеста (таймауты, блокировки)
"""

import sys
sys.path.insert(0, '.')

import yaml
from core.manifest_generator import ManifestAutomationGenerator, TriggerMapping
from core.fsm import FSMDefinition


def create_test_manifest():
    """Создаёт тестовый манифест"""
    return {
        "version": 1,
        "instance": {
            "id": "test_house",
            "name": "Test House"
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
                },
                {
                    "id": "light.living_room",
                    "name": "Living Room Light",
                    "room": "living_room",
                    "motion_sensor": "binary_sensor.living_room_motion",
                    "schedule": "08:00-23:30",
                    "motion_timeout_sec": 600
                }
            ],
            "climate": [
                {
                    "id": "climate.living_room",
                    "name": "Living Room Climate",
                    "room": "living_room",
                    "sensor": "sensor.living_room_temperature",
                    "target": 22.0,
                    "hysteresis": 0.5,
                    "modes": ["heat", "cool", "auto"]
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
            "climate": {"manual_lockout_min": 30},
            "ventilation": {"manual_lockout_min": 15}
        },
        "dashboard": {"title": "Test House"}
    }


def test_generator_creates_lighting_definitions():
    """Генератор создаёт автоматы освещения"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    assert len(result.lighting_definitions) == 2
    assert all(isinstance(d, FSMDefinition) for d in result.lighting_definitions)
    print("✅ test_generator_creates_lighting_definitions")


def test_generator_creates_lighting_mappings():
    """Генератор создаёт маппинги освещения"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    # 2 устройства * 2 маппинга (on/off) = 4 маппинга
    assert len(result.lighting_mappings) == 4
    assert all(isinstance(m, TriggerMapping) for m in result.lighting_mappings)
    print("✅ test_generator_creates_lighting_mappings")


def test_generator_creates_climate_definitions():
    """Генератор создаёт автоматы климата"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    assert len(result.climate_definitions) == 1
    assert isinstance(result.climate_definitions[0], FSMDefinition)
    print("✅ test_generator_creates_climate_definitions")


def test_generator_creates_ventilation_definitions():
    """Генератор создаёт автоматы вентиляции"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    assert len(result.ventilation_definitions) == 1
    assert isinstance(result.ventilation_definitions[0], FSMDefinition)
    print("✅ test_generator_creates_ventilation_definitions")


def test_generator_respects_motion_timeout():
    """Генератор использует таймаут из манифеста"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    # Ищем автомат с timeout_sec = 300
    kitchen_def = next((d for d in result.lighting_definitions if d.entity_id == "light.kitchen"), None)
    assert kitchen_def is not None
    
    # Проверяем что есть переход с timeout_sec=300
    timeout_transitions = [t for t in kitchen_def.transitions if t.timeout_sec == 300]
    assert len(timeout_transitions) > 0
    print("✅ test_generator_respects_motion_timeout")


def test_generator_respects_manual_lockout():
    """Генератор использует блокировку из манифеста"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    # Ищем переход с manual_lockout_min
    lighting_def = result.lighting_definitions[0]
    manual_transitions = [t for t in lighting_def.transitions if t.manual_lockout_min > 0]
    assert len(manual_transitions) > 0
    assert manual_transitions[0].manual_lockout_min == 60  # из automation_rules
    print("✅ test_generator_respects_manual_lockout")


def test_generator_handles_empty_devices_list():
    """Пустой список устройств не вызывает ошибок"""
    manifest = {
        "version": 1,
        "instance": {"id": "empty", "name": "Empty"},
        "devices": {
            "lighting": [],
            "climate": [],
            "ventilation": []
        },
        "zones": [],
        "automation_rules": {}
    }
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    assert len(result.lighting_definitions) == 0
    assert len(result.climate_definitions) == 0
    assert len(result.ventilation_definitions) == 0
    print("✅ test_generator_handles_empty_devices_list")


def test_generator_handles_missing_motion_sensor():
    """Устройство без motion_sensor обрабатывается корректно"""
    manifest = create_test_manifest()
    manifest["devices"]["lighting"][0]["motion_sensor"] = None
    del manifest["devices"]["lighting"][0]["motion_sensor"]
    
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    # Автомат должен создаться, но маппингов для этого устройства не будет
    assert len(result.lighting_definitions) == 2
    print("✅ test_generator_handles_missing_motion_sensor")


def test_generator_all_entities_in_registry():
    """Все entity_id имеют правильный формат"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    import re
    entity_pattern = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
    
    # Проверяем все entity_id из определений
    for defn in result.lighting_definitions + result.climate_definitions + result.ventilation_definitions:
        assert entity_pattern.match(defn.entity_id), f"Invalid entity_id: {defn.entity_id}"
    
    # Проверяем все source_entity из маппингов
    for mapping in result.lighting_mappings + result.climate_mappings + result.ventilation_mappings:
        assert entity_pattern.match(mapping.source_entity), f"Invalid source_entity: {mapping.source_entity}"
    
    print("✅ test_generator_all_entities_in_registry")


def test_generator_extracts_automation_rules():
    """Правила автоматизации извлекаются из манифеста"""
    manifest = create_test_manifest()
    generator = ManifestAutomationGenerator(manifest)
    result = generator.generate_all()
    
    assert "lighting" in result.automation_rules
    assert "climate" in result.automation_rules
    assert "ventilation" in result.automation_rules
    assert result.automation_rules["lighting"]["manual_lockout_min"] == 60
    print("✅ test_generator_extracts_automation_rules")


if __name__ == "__main__":
    print("Running generator tests...\n")
    
    test_generator_creates_lighting_definitions()
    test_generator_creates_lighting_mappings()
    test_generator_creates_climate_definitions()
    test_generator_creates_ventilation_definitions()
    test_generator_respects_motion_timeout()
    test_generator_respects_manual_lockout()
    test_generator_handles_empty_devices_list()
    test_generator_handles_missing_motion_sensor()
    test_generator_all_entities_in_registry()
    test_generator_extracts_automation_rules()
    
    print("\n" + "="*50)
    print("All 10 generator tests passed! ✅")
