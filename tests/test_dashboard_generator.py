"""
Тесты генератора дашбордов.

Проверяют что DashboardGenerator корректно создаёт карточки Lovelace
из манифеста.
"""

import pytest
import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

# Импортируем тестируемые модули
from tools.dashboard_generator import DashboardGenerator


@pytest.fixture
def sample_manifest():
    """Пример валидного манифеста для тестов"""
    return {
        "version": 1,
        "instance": {
            "id": "test_house",
            "name": "Test House",
            "owner": "Test User",
        },
        "devices": {
            "lighting": [
                {
                    "id": "light.kitchen",
                    "name": "Свет на кухне",
                    "room": "kitchen",
                    "motion_sensor": "binary_sensor.kitchen_motion",
                    "schedule": "07:00-23:00",
                    "motion_timeout_sec": 300,
                },
                {
                    "id": "light.living_room",
                    "name": "Свет в гостиной",
                    "room": "living_room",
                    "motion_sensor": "binary_sensor.living_room_motion",
                    "schedule": "08:00-23:30",
                    "motion_timeout_sec": 600,
                },
            ],
            "climate": [
                {
                    "id": "climate.kitchen",
                    "name": "Климат кухни",
                    "room": "kitchen",
                    "sensor": "sensor.kitchen_temperature",
                    "target": 22.0,
                    "hysteresis": 0.5,
                }
            ],
            "ventilation": [
                {
                    "id": "fan.bathroom",
                    "name": "Вентиляция ванной",
                    "room": "bathroom",
                    "humidity_sensor": "sensor.bathroom_humidity",
                    "humidity_threshold": 65,
                    "timeout_sec": 1800,
                }
            ],
        },
        "zones": [
            {"id": "kitchen", "name": "Кухня", "floor": 1},
            {"id": "living_room", "name": "Гостиная", "floor": 1},
            {"id": "bathroom", "name": "Ванная", "floor": 1},
        ],
        "automation_rules": {
            "lighting": {"manual_lockout_min": 60},
            "climate": {"manual_lockout_min": 30},
        },
        "dashboard": {
            "title": "Test House Dashboard",
            "show_motion_sensors": True,
            "show_climate": True,
            "show_history": True,
            "history_days": 7,
        },
    }


@pytest.fixture
def generator(sample_manifest):
    """Создаёт генератор для тестов"""
    return DashboardGenerator(sample_manifest)


class TestDashboardGeneratorBasics:
    """Базовые тесты генератора"""

    def test_generator_initialization(self, sample_manifest):
        """Тест: генератор успешно инициализируется"""
        gen = DashboardGenerator(sample_manifest)
        assert gen._manifest == sample_manifest

    def test_generator_handles_empty_manifest(self):
        """Тест: пустой манифест не вызывает падений"""
        empty_manifest = {
            "version": 1,
            "instance": {"id": "empty", "name": "Empty"},
            "devices": {},
            "zones": [],
            "dashboard": {},
        }
        gen = DashboardGenerator(empty_manifest)
        dashboard = gen.generate_full_dashboard()
        assert dashboard is not None
        assert "views" in dashboard


class TestAutomationsStatusCard:
    """Тесты карточки статуса автоматов"""

    def test_generator_creates_status_card(self, generator):
        """Тест: карточка статуса создаётся"""
        card = generator.generate_automations_status_card()
        assert card is not None
        assert "type" in card
        assert card["type"] == "entities"
        assert "title" in card
        assert "entities" in card

    def test_generator_includes_all_devices(self, generator, sample_manifest):
        """Тест: все устройства из манифеста в карточке"""
        card = generator.generate_automations_status_card()

        # Считаем общее количество устройств
        total_devices = sum(
            len(sample_manifest["devices"].get(device_type, []))
            for device_type in ["lighting", "climate", "ventilation"]
        )

        assert len(card["entities"]) == total_devices

    def test_generator_uses_correct_icons(self, generator):
        """Тест: иконки правильные для каждого типа устройства"""
        card = generator.generate_automations_status_card()

        icons_found = {entity["icon"] for entity in card["entities"]}

        # Проверяем что есть иконки для разных типов устройств
        assert "mdi:lightbulb" in icons_found  # освещение
        assert "mdi:thermometer" in icons_found  # климат
        assert "mdi:fan" in icons_found  # вентиляция

    def test_generator_entity_ids_format(self, generator):
        """Тест: entity_id сенсоров сформированы корректно"""
        card = generator.generate_automations_status_card()

        for entity in card["entities"]:
            assert entity["entity"].startswith("sensor.platform_v3_")
            assert entity["entity"].endswith("_state")
            # Проверяем что нет точек в entity_id после преобразования
            assert "." not in entity["entity"].split("sensor.platform_v3_")[1]


class TestControlCard:
    """Тесты карточки управления"""

    def test_control_card_generated(self, generator):
        """Тест: карточка управления создаётся"""
        card = generator.generate_control_card()
        assert card is not None
        assert card["type"] == "horizontal-stack"
        assert "cards" in card

    def test_control_card_has_all_buttons(self, generator):
        """Тест: все кнопки управления присутствуют"""
        card = generator.generate_control_card()

        button_names = [btn["name"] for btn in card["cards"]]

        expected_buttons = ["Включить", "Выключить", "Ручной", "Статус", "Сброс"]
        for expected in expected_buttons:
            assert expected in button_names

    def test_control_card_calls_correct_services(self, generator):
        """Тест: кнопки вызывают правильные сервисы"""
        card = generator.generate_control_card()

        services_called = {
            btn["tap_action"]["service"] for btn in card["cards"]
        }

        expected_services = {
            "platform_v3.enable_automation",
            "platform_v3.disable_automation",
            "platform_v3.manual_mode",
            "platform_v3.status",
            "platform_v3.reset_lockouts",
        }

        assert services_called == expected_services


class TestHistoryCard:
    """Тесты карточки истории"""

    def test_history_card_generated(self, generator):
        """Тест: карточка истории создаётся"""
        card = generator.generate_history_card()
        assert card is not None
        assert "type" in card
        assert "entities" in card

    def test_history_card_respects_days_setting(self, sample_manifest):
        """Тест: настройка history_days из манифеста применяется"""
        sample_manifest["dashboard"]["history_days"] = 14
        gen = DashboardGenerator(sample_manifest)
        card = gen.generate_history_card()

        assert "14 дн." in card["title"]

    def test_history_card_sorted_by_time(self, generator):
        """Тест: сортировка по времени включена"""
        card = generator.generate_history_card()

        assert "sort" in card
        assert card["sort"]["method"] == "last_changed"
        assert card["sort"]["reverse"] is True


class TestMotionSensorsCard:
    """Тесты карточки датчиков движения"""

    def test_motion_card_generated_when_enabled(self, generator):
        """Тест: карточка датчиков создаётся когда включено"""
        card = generator.generate_motion_sensors_card()
        assert card is not None
        assert "entities" in card

    def test_motion_card_not_generated_when_disabled(self, sample_manifest):
        """Тест: карточка не создаётся когда выключено"""
        sample_manifest["dashboard"]["show_motion_sensors"] = False
        gen = DashboardGenerator(sample_manifest)
        card = gen.generate_motion_sensors_card()
        assert card is None

    def test_motion_card_no_duplicates(self, generator, sample_manifest):
        """Тест: датчики движения без дубликатов"""
        card = generator.generate_motion_sensors_card()

        entities = [e["entity"] for e in card["entities"]]
        assert len(entities) == len(set(entities)), "Дубликаты датчиков!"


class TestClimateCard:
    """Тесты карточки климата"""

    def test_climate_card_generated_when_enabled(self, generator):
        """Тест: карточка климата создаётся когда включено"""
        card = generator.generate_climate_overview_card()
        assert card is not None

    def test_climate_card_not_generated_when_disabled(self, sample_manifest):
        """Тест: карточка климата не создаётся когда выключено"""
        sample_manifest["dashboard"]["show_climate"] = False
        gen = DashboardGenerator(sample_manifest)
        card = gen.generate_climate_overview_card()
        assert card is None


class TestFullDashboard:
    """Тесты полного дашборда"""

    def test_dashboard_full_generated(self, generator):
        """Тест: полный дашборд создаётся"""
        dashboard = generator.generate_full_dashboard()

        assert dashboard is not None
        assert "title" in dashboard
        assert "views" in dashboard
        assert len(dashboard["views"]) > 0

    def test_dashboard_has_main_view(self, generator):
        """Тест: главная страница присутствует"""
        dashboard = generator.generate_full_dashboard()

        main_view = next(
            (v for v in dashboard["views"] if v["title"] == "Главная"), None
        )
        assert main_view is not None
        assert "cards" in main_view

    def test_dashboard_has_history_view_when_enabled(self, generator):
        """Тест: страница истории присутствует когда включено"""
        dashboard = generator.generate_full_dashboard()

        history_view = next(
            (v for v in dashboard["views"] if v["title"] == "История"), None
        )
        assert history_view is not None

    def test_dashboard_has_rooms_view_when_zones_exist(self, generator):
        """Тест: страница комнат присутствует когда есть зоны"""
        dashboard = generator.generate_full_dashboard()

        rooms_view = next(
            (v for v in dashboard["views"] if v["title"] == "Комнаты"), None
        )
        assert rooms_view is not None

    def test_dashboard_respects_dashboard_settings(self, sample_manifest):
        """Тест: настройки дашборда из манифеста применяются"""
        sample_manifest["dashboard"]["title"] = "Custom Title"
        gen = DashboardGenerator(sample_manifest)
        dashboard = gen.generate_full_dashboard()

        assert dashboard["title"] == "Custom Title"


class TestWriteToHA:
    """Тесты записи в HA"""

    def test_dashboard_written_to_file(self, generator, sample_manifest):
        """Тест: файл дашборда записывается"""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "ui-lovelace.yaml"

            result = generator.write_to_ha(output_path=str(output_path))

            assert result is True
            assert output_path.exists()

            with open(output_path, "r") as f:
                content = yaml.safe_load(f)

            assert "platform_v3_dashboard" in content

    def test_dashboard_preserves_existing_content(self, generator):
        """Тест: существующее содержимое не теряется"""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "ui-lovelace.yaml"

            # Создаём файл с существующим содержимым
            existing_content = {
                "existing_key": "existing_value",
                "another_key": {"nested": "data"},
            }
            with open(output_path, "w") as f:
                yaml.dump(existing_content, f)

            # Записываем дашборд
            generator.write_to_ha(output_path=str(output_path))

            # Читаем обратно
            with open(output_path, "r") as f:
                content = yaml.safe_load(f)

            # Проверяем что старое содержимое сохранилось
            assert content["existing_key"] == "existing_value"
            assert content["another_key"]["nested"] == "data"
            assert "platform_v3_dashboard" in content

    def test_dashboard_updates_on_manifest_change(self, sample_manifest):
        """Тест: при изменении манифеста дашборд обновляется"""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "ui-lovelace.yaml"

            # Генерируем первый дашборд
            gen1 = DashboardGenerator(sample_manifest)
            gen1.write_to_ha(output_path=str(output_path))

            # Меняем манифест
            sample_manifest["dashboard"]["title"] = "Updated Title"
            gen2 = DashboardGenerator(sample_manifest)
            gen2.write_to_ha(output_path=str(output_path))

            # Читаем обратно
            with open(output_path, "r") as f:
                content = yaml.safe_load(f)

            assert content["platform_v3_dashboard"]["title"] == "Updated Title"


class TestGenerateAndSave:
    """Тесты сохранения в файл"""

    def test_generate_and_save_creates_file(self, generator):
        """Тест: файл сохраняется в директорию"""
        with TemporaryDirectory() as tmpdir:
            result_path = generator.generate_and_save(output_dir=tmpdir)

            assert result_path.exists()
            assert result_path.suffix == ".yaml"

    def test_generate_and_save_custom_filename(self, generator):
        """Тест: можно указать своё имя файла"""
        with TemporaryDirectory() as tmpdir:
            result_path = generator.generate_and_save(
                output_dir=tmpdir, filename="custom_dashboard.yaml"
            )

            assert result_path.name == "custom_dashboard.yaml"


class TestValidateDashboardConfig:
    """Тесты валидации конфигурации дашборда"""

    def test_validate_passes_valid_config(self, generator):
        """Тест: валидная конфигурация проходит"""
        errors = generator.validate_dashboard_config()
        assert len(errors) == 0

    def test_validate_catches_missing_title(self, sample_manifest):
        """Тест: отсутствует title → ошибка"""
        del sample_manifest["dashboard"]["title"]
        gen = DashboardGenerator(sample_manifest)
        errors = gen.validate_dashboard_config()

        assert any("title" in err for err in errors)

    def test_validate_catches_invalid_history_days(self, sample_manifest):
        """Тест: history_days вне диапазона → ошибка"""
        sample_manifest["dashboard"]["history_days"] = 500
        gen = DashboardGenerator(sample_manifest)
        errors = gen.validate_dashboard_config()

        assert any("history_days" in err for err in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
