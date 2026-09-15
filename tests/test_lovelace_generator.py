"""Тесты для генератора дашбордов Lovelace."""

import pytest
import yaml

from core import (
    BehaviorConfig,
    Dashboard,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
    load_manifest,
)
from dashboard import LovelaceGenerator


@pytest.fixture
def test_manifest_with_behaviors(tmp_path):
    """Создать тестовый манифест с устройствами и поведениями."""
    manifest_content = """
version: 1
instance:
  id: test_house
  name: "Test House"
  owner: Test User
  created_at: '2024-01-01'
rooms:
  - id: kitchen
    name: Kitchen
    sensors:
      motion: binary_sensor.kitchen_motion
    devices:
      - id: light.kitchen
        name: Kitchen Light
        type: light
        behaviors:
          - template: motion_detection
            priority: 1
            params:
              timeout: 300
          - template: night_mode
            priority: 2
            params:
              brightness: 10
  - id: living_room
    name: Living Room
    sensors:
      temperature: sensor.living_room_temperature
    devices:
      - id: climate.living_room
        type: climate
        name: Living Room Climate
        behaviors:
          - template: eco_mode
            priority: 1
            params:
              eco_temp: 18
  - id: bathroom
    name: Bathroom
    sensors:
      humidity: sensor.bathroom_humidity
    devices:
      - id: fan.bathroom
        type: ventilation
        name: Bathroom Fan
        behaviors:
          - template: humidity_control
            priority: 1
            params:
              threshold: 65
automation_rules:
  lighting:
    motion_enabled: true
    schedule_enabled: true
    manual_lockout_min: 60
  climate:
    safety_lockout_enabled: true
    manual_lockout_min: 90
  ventilation:
    humidity_based: true
    manual_lockout_min: 15
dashboard:
  title: Test Dashboard
"""
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(manifest_content)
    return load_manifest(str(manifest_path))


@pytest.fixture
def sample_manifest():
    return Manifest(
        instance=InstanceConfig(id="test", name="Test House"),
        rooms=[
            RoomConfig(
                id="kitchen",
                name="Kitchen",
                sensors={"motion": "binary_sensor.kitchen_motion"},
                devices=[
                    DeviceConfig(
                        id="light.kitchen",
                        type="light_motion",
                        behaviors=[
                            BehaviorConfig(template="lighting", priority=10),
                        ],
                    ),
                ],
            ),
        ],
        dashboard=Dashboard(title="Test Dashboard", rooms=["kitchen"]),
    )


@pytest.fixture
def generator():
    """Создать экземпляр генератора."""
    return LovelaceGenerator()


class TestLovelaceGenerator:
    """Тесты для LovelaceGenerator."""

    def test_generate_returns_dict(self, generator, test_manifest_with_behaviors):
        """Проверка, что generate возвращает dict."""
        result = generator.generate(test_manifest_with_behaviors)
        assert isinstance(result, dict)

    def test_generate_has_title(self, generator, test_manifest_with_behaviors):
        """Проверка, что дашборд имеет заголовок из манифеста."""
        result = generator.generate(test_manifest_with_behaviors)
        assert result["title"] == "Test Dashboard"

    def test_generate_has_views(self, generator, test_manifest_with_behaviors):
        """Проверка, что дашборд имеет вкладки."""
        result = generator.generate(test_manifest_with_behaviors)
        assert "views" in result
        assert isinstance(result["views"], list)
        # Должно быть 3 вкладки (по количеству зон)
        assert len(result["views"]) == 3

    def test_views_have_zone_titles(self, generator, test_manifest_with_behaviors):
        """Проверка, что вкладки имеют названия зон."""
        result = generator.generate(test_manifest_with_behaviors)
        view_titles = [view["title"] for view in result["views"]]
        assert "Kitchen" in view_titles
        assert "Living Room" in view_titles
        assert "Bathroom" in view_titles

    def test_views_have_zone_paths(self, generator, test_manifest_with_behaviors):
        """Проверка, что вкладки имеют пути zone.id."""
        result = generator.generate(test_manifest_with_behaviors)
        view_paths = [view["path"] for view in result["views"]]
        assert "kitchen" in view_paths
        assert "living_room" in view_paths
        assert "bathroom" in view_paths

        view_titles = [v["title"] for v in result["views"]]
        assert "Kitchen" in view_titles
        assert "Living Room" in view_titles
        assert "Bathroom" in view_titles  # комната называется "Bathroom"

    def test_kitchen_view_has_device_cards(self, generator, test_manifest_with_behaviors):
        """Проверка, что вкладка кухни имеет карточку устройства."""
        result = generator.generate(test_manifest_with_behaviors)
        kitchen_view = next(v for v in result["views"] if v["path"] == "kitchen")
        assert len(kitchen_view["cards"]) > 0

    def test_device_control_card_exists(self, generator, test_manifest_with_behaviors):
        """Проверка, что для каждого устройства создана карточка управления."""
        result = generator.generate(test_manifest_with_behaviors)

        # Проверяем каждую зону
        for view in result["views"]:
            if view["path"] == "kitchen":
                # Kitchen Light должен иметь карточку управления
                control_cards = [c for c in view["cards"] if c.get("type") == "entities"]
                assert len(control_cards) >= 1

        # Проверяем living_room с climate устройством
        living_room_view = next(v for v in result["views"] if v["path"] == "living_room")
        thermostat_cards = [c for c in living_room_view["cards"] if c.get("type") == "thermostat"]
        assert len(thermostat_cards) >= 1

    def test_behavior_indicators_exist(self, generator, test_manifest_with_behaviors):
        """Проверка, что для каждого behavior создан индикатор активности."""
        result = generator.generate(test_manifest_with_behaviors)

        # Считаем количество behavior indicator карточек
        behavior_indicators = []
        for view in result["views"]:
            for card in view["cards"]:
                if card.get("type") == "entity-button":
                    behavior_indicators.append(card)

        # У нас 4 behavior в манифесте:
        # - Kitchen Light: motion_detection, night_mode (2)
        # - Living Room Climate: eco_mode (1)
        # - Bathroom Fan: humidity_control (1)
        assert len(behavior_indicators) == 4

    def test_behavior_indicator_has_priority(self, generator, test_manifest_with_behaviors):
        """Проверка, что индикатор поведения содержит информацию о приоритете."""
        result = generator.generate(test_manifest_with_behaviors)

        for view in result["views"]:
            for card in view["cards"]:
                if card.get("type") == "entity-button":
                    name = card.get("name", "")
                    assert "приоритет" in name or "priority" in name.lower()

    def test_yaml_serializable(self, generator, test_manifest_with_behaviors):
        """Проверка, что результат может быть сериализован в YAML."""
        result = generator.generate(test_manifest_with_behaviors)
        yaml_output = yaml.dump(result, default_flow_style=False, allow_unicode=True)
        assert yaml_output is not None
        assert len(yaml_output) > 0

        # Проверяем, что YAML валидный
        parsed = yaml.safe_load(yaml_output)
        assert parsed == result

    def test_all_devices_have_cards(self, generator, test_manifest_with_behaviors):
        """Проверка, что все устройства из манифеста имеют карточки."""
        result = generator.generate(test_manifest_with_behaviors)

        # Собираем все названия устройств из карточек
        device_names_in_cards = set()
        for view in result["views"]:
            for card in view["cards"]:
                if card.get("type") == "entities" and card.get("title"):
                    device_names_in_cards.add(card["title"])
                elif card.get("type") == "thermostat" and card.get("name"):
                    device_names_in_cards.add(card["name"])

        # Проверяем, что все устройства представлены
        expected_devices = {"Kitchen Light", "Living Room Climate", "Bathroom Fan"}
        assert expected_devices.issubset(device_names_in_cards)

    def test_empty_zone_handling(self, tmp_path, generator):
        """Проверка обработки зоны без устройств."""
        manifest_content = """
    version: 1
    instance:
      id: test_house
      name: "Test House"
      owner: Test User
      created_at: '2024-01-01'
    rooms:
      - id: empty_room
        name: Empty Room
        sensors: {}
        devices: []
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
      title: "Test House Dashboard"
    """
        manifest_path = tmp_path / "empty_manifest.yaml"
        manifest_path.write_text(manifest_content)
        manifest = load_manifest(str(manifest_path))

        result = generator.generate(manifest)
        empty_view = next(v for v in result["views"] if v["path"] == "empty_room")
        # В пустой зоне должна быть markdown карточка
        assert any(c.get("type") == "markdown" for c in empty_view["cards"])

    def test_entity_id_generation(self, generator, test_manifest_with_behaviors):
        """Проверка корректной генерации entity_id."""
        result = generator.generate(test_manifest_with_behaviors)

        # Проверяем, что entity_id имеют правильный формат
        for view in result["views"]:
            for card in view["cards"]:
                if card.get("type") == "entities" and card.get("entities"):
                    for entity in card["entities"]:
                        entity_id = entity.get("entity", "")
                        assert "." in entity_id  # domain.entity_id format

                if card.get("type") == "thermostat":
                    entity_id = card.get("entity", "")
                    assert "." in entity_id

    def test_complete_dashboard_structure(self, generator, test_manifest_with_behaviors):
        """Проверка полной структуры дашборда."""
        result = generator.generate(test_manifest_with_behaviors)

        # Проверка верхнеуровневой структуры
        assert "title" in result
        assert "views" in result

        # Проверка структуры каждой вкладки
        for view in result["views"]:
            assert "title" in view
            assert "path" in view
            assert "cards" in view
            assert isinstance(view["cards"], list)

            # Проверка структуры каждой карточки
            for card in view["cards"]:
                assert "type" in card
