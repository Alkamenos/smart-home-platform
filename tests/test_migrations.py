"""Тесты для системы миграций манифестов."""

import pytest

from smart_home.migrations import Migration
from smart_home.migrations.runner import MigrationRunner
from smart_home.migrations._001_convert_devices_to_flat_list import (
    Migration001ConvertDevicesToFlatList,
)


class TestMigrationBaseClass:
    """Тесты базового класса Migration."""
    
    def test_migration_is_abstract(self):
        """Базовый класс Migration должен быть абстрактным."""
        # Попытка создать экземпляр базового класса должна вызвать ошибку
        with pytest.raises(TypeError):
            Migration()
    
    def test_migration_subclass_must_implement_up(self):
        """Подкласс должен реализовать метод up."""
        class IncompleteMigration(Migration):
            def down(self, manifest: dict) -> dict:
                return manifest
        
        with pytest.raises(TypeError):
            IncompleteMigration()
    
    def test_migration_subclass_must_implement_down(self):
        """Подкласс должен реализовать метод down."""
        class IncompleteMigration(Migration):
            def up(self, manifest: dict) -> dict:
                return manifest
        
        with pytest.raises(TypeError):
            IncompleteMigration()


class TestMigration001:
    """Тесты для первой миграции конвертации устройств."""
    
    @pytest.fixture
    def old_format_manifest(self) -> dict:
        """Манифест в старом формате (устройства внутри зон)."""
        return {
            "instance": {
                "id": "home_001",
                "name": "Test Home",
                "owner": "John Doe",
                "created_at": "2024-01-01"
            },
            "zones": [
                {
                    "id": "living_room",
                    "name": "Гостиная",
                    "floor": 1,
                    "devices": [
                        {
                            "id": "light_1",
                            "name": "Свет 1",
                            "type": "light_motion",
                            "behaviors": [
                                {"template": "motion_light.yaml", "priority": 1}
                            ]
                        },
                        {
                            "id": "light_2",
                            "name": "Свет 2",
                            "type": "light_motion",
                            "behaviors": []
                        }
                    ]
                },
                {
                    "id": "bedroom",
                    "name": "Спальня",
                    "floor": 2,
                    "devices": [
                        {
                            "id": "climate_1",
                            "name": "Кондиционер",
                            "type": "climate_hysteresis",
                            "behaviors": [
                                {"template": "climate.yaml", "priority": 2, "params": {"temp": 22}}
                            ]
                        }
                    ]
                }
            ],
            "automation_rules": {
                "lighting": {
                    "motion_enabled": True,
                    "schedule_enabled": True,
                    "manual_lockout_min": 5
                },
                "climate": {
                    "safety_lockout_enabled": True,
                    "away_mode_enabled": True,
                    "manual_lockout_min": 10
                },
                "ventilation": {
                    "humidity_based": True,
                    "manual_lockout_min": 5
                }
            },
            "dashboard": {
                "title": "Dashboard",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
    
    @pytest.fixture
    def new_format_manifest(self) -> dict:
        """Манифест в новом формате (плоский список устройств)."""
        return {
            "version": 1,
            "instance": {
                "id": "home_001",
                "name": "Test Home",
                "owner": "John Doe",
                "created_at": "2024-01-01"
            },
            "zones": [
                {"id": "living_room", "name": "Гостиная", "floor": 1},
                {"id": "bedroom", "name": "Спальня", "floor": 2}
            ],
            "devices": [
                {
                    "id": "light_1",
                    "name": "Свет 1",
                    "type": "light_motion",
                    "room": "living_room",
                    "behaviors": [
                        {"template": "motion_light.yaml", "priority": 1}
                    ]
                },
                {
                    "id": "light_2",
                    "name": "Свет 2",
                    "type": "light_motion",
                    "room": "living_room",
                    "behaviors": []
                },
                {
                    "id": "climate_1",
                    "name": "Кондиционер",
                    "type": "climate_hysteresis",
                    "room": "bedroom",
                    "behaviors": [
                        {"template": "climate.yaml", "priority": 2, "params": {"temp": 22}}
                    ]
                }
            ],
            "automation_rules": {
                "lighting": {
                    "motion_enabled": True,
                    "schedule_enabled": True,
                    "manual_lockout_min": 5
                },
                "climate": {
                    "safety_lockout_enabled": True,
                    "away_mode_enabled": True,
                    "manual_lockout_min": 10
                },
                "ventilation": {
                    "humidity_based": True,
                    "manual_lockout_min": 5
                }
            },
            "dashboard": {
                "title": "Dashboard",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
    
    def test_migration_up_converts_old_to_new_format(
        self, old_format_manifest: dict, new_format_manifest: dict
    ):
        """Миграция up конвертирует старый формат в новый."""
        migration = Migration001ConvertDevicesToFlatList()
        
        result = migration.up(old_format_manifest)
        
        # Проверяем версию
        assert result["version"] == 1
        
        # Проверяем зоны (теперь без устройств)
        assert len(result["zones"]) == 2
        assert result["zones"][0]["id"] == "living_room"
        assert result["zones"][0]["name"] == "Гостиная"
        assert result["zones"][0]["floor"] == 1
        assert "devices" not in result["zones"][0]
        
        # Проверяем устройства (плоский список)
        assert "devices" in result
        assert len(result["devices"]) == 3
        
        # Проверяем, что устройства имеют поле room
        light_1 = next(d for d in result["devices"] if d["id"] == "light_1")
        assert light_1["room"] == "living_room"
        assert light_1["type"] == "light_motion"
        
        climate_1 = next(d for d in result["devices"] if d["id"] == "climate_1")
        assert climate_1["room"] == "bedroom"
        assert climate_1["type"] == "climate_hysteresis"
    
    def test_migration_down_reverts_new_to_old_format(
        self, old_format_manifest: dict, new_format_manifest: dict
    ):
        """Миграция down откатывает новый формат к старому."""
        migration = Migration001ConvertDevicesToFlatList()
        
        result = migration.down(new_format_manifest)
        
        # Проверяем, что устройства удалены из корневого уровня
        assert "devices" not in result
        
        # Проверяем, что устройства вернулись в зоны
        living_room = next(z for z in result["zones"] if z["id"] == "living_room")
        assert "devices" in living_room
        assert len(living_room["devices"]) == 2
        
        bedroom = next(z for z in result["zones"] if z["id"] == "bedroom")
        assert "devices" in bedroom
        assert len(bedroom["devices"]) == 1
        
        # Проверяем, что у устройств нет поля room
        device = living_room["devices"][0]
        assert "room" not in device
    
    def test_migration_roundtrip(self, old_format_manifest: dict):
        """Применение и откат миграции возвращает исходный формат."""
        migration = Migration001ConvertDevicesToFlatList()
        
        # Применяем миграцию
        migrated = migration.up(old_format_manifest)
        
        # Откатываем миграцию
        reverted = migration.down(migrated)
        
        # Проверяем, что структура вернулась к исходной
        assert "devices" not in reverted
        assert len(reverted["zones"]) == len(old_format_manifest["zones"])
        
        # Проверяем количество устройств в зонах
        for orig_zone in old_format_manifest["zones"]:
            reverted_zone = next(
                z for z in reverted["zones"] if z["id"] == orig_zone["id"]
            )
            assert len(reverted_zone.get("devices", [])) == len(orig_zone.get("devices", []))


class TestMigrationRunner:
    """Тесты для MigrationRunner."""
    
    @pytest.fixture
    def runner(self) -> MigrationRunner:
        """Создать экземпляр MigrationRunner."""
        return MigrationRunner()
    
    @pytest.fixture
    def old_manifest_no_version(self) -> dict:
        """Старый манифест без версии."""
        return {
            "instance": {"id": "test", "name": "Test", "owner": "Test", "created_at": "2024-01-01"},
            "zones": [
                {
                    "id": "room1",
                    "name": "Room 1",
                    "devices": [
                        {"id": "dev1", "name": "Device 1", "type": "light_motion"}
                    ]
                }
            ],
            "automation_rules": {
                "lighting": {"motion_enabled": True, "schedule_enabled": True, "manual_lockout_min": 5},
                "climate": {"safety_lockout_enabled": True, "away_mode_enabled": True, "manual_lockout_min": 10},
                "ventilation": {"humidity_based": True, "manual_lockout_min": 5}
            },
            "dashboard": {
                "title": "Test",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
    
    def test_runner_discovers_migrations(self, runner: MigrationRunner):
        """Runner должен обнаружить все доступные миграции."""
        assert len(runner.migrations) >= 1
        
        # Проверяем, что первая миграция найдена
        migration_versions = [m.version for m in runner.migrations]
        assert 1 in migration_versions
    
    def test_runner_get_current_version(self, runner: MigrationRunner):
        """Получение текущей версии манифеста."""
        assert runner.get_current_version({}) == 0
        assert runner.get_current_version({"version": 1}) == 1
        assert runner.get_current_version({"version": 5}) == 5
    
    def test_runner_apply_migrates_old_manifest(
        self, runner: MigrationRunner, old_manifest_no_version: dict
    ):
        """Применение миграций к старому манифесту."""
        result = runner.apply(old_manifest_no_version)
        
        # Манифест должен быть обновлен до последней версии
        assert result["version"] == runner.get_target_version()
        
        # Устройства должны быть в плоском списке
        assert "devices" in result
        assert isinstance(result["devices"], list)
        assert len(result["devices"]) == 1
        
        # Устройство должно иметь поле room
        assert result["devices"][0]["room"] == "room1"
        
        # Зоны не должны содержать устройства
        for zone in result["zones"]:
            assert "devices" not in zone
    
    def test_runner_migrate_method(self, runner: MigrationRunner, old_manifest_no_version: dict):
        """Метод migrate автоматически применяет миграции."""
        result = runner.migrate(old_manifest_no_version)
        
        # Должен работать так же как apply
        assert result["version"] == runner.get_target_version()
        assert "devices" in result
        assert result["devices"][0]["room"] == "room1"
    
    def test_runner_skip_already_migrated(self, runner: MigrationRunner):
        """Runner должен пропускать уже мигрированные манифесты."""
        new_manifest = {
            "version": 1,
            "instance": {"id": "test", "name": "Test", "owner": "Test", "created_at": "2024-01-01"},
            "zones": [{"id": "room1", "name": "Room 1", "floor": 1}],
            "devices": [{"id": "dev1", "name": "Device 1", "type": "light_motion", "room": "room1"}],
            "automation_rules": {
                "lighting": {"motion_enabled": True, "schedule_enabled": True, "manual_lockout_min": 5},
                "climate": {"safety_lockout_enabled": True, "away_mode_enabled": True, "manual_lockout_min": 10},
                "ventilation": {"humidity_based": True, "manual_lockout_min": 5}
            },
            "dashboard": {
                "title": "Test",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
        
        result = runner.apply(new_manifest)
        
        # Манифест должен остаться неизменным
        assert result is new_manifest or result == new_manifest


class TestIntegrationWithManifest:
    """Интеграционные тесты с моделью Manifest."""
    
    def test_migrated_manifest_validates_with_pydantic(self):
        """Мигрированный манифест должен проходить валидацию Pydantic."""
        from smart_home.core.models.manifest import Manifest
        
        runner = MigrationRunner()
        
        old_manifest = {
            "instance": {"id": "test", "name": "Test", "owner": "Test", "created_at": "2024-01-01"},
            "zones": [
                {
                    "id": "living_room",
                    "name": "Гостиная",
                    "devices": [
                        {
                            "id": "light_1",
                            "name": "Light",
                            "type": "light_motion",
                            "behaviors": [{"template": "motion.yaml", "priority": 1}]
                        }
                    ]
                }
            ],
            "automation_rules": {
                "lighting": {"motion_enabled": True, "schedule_enabled": True, "manual_lockout_min": 5},
                "climate": {"safety_lockout_enabled": True, "away_mode_enabled": True, "manual_lockout_min": 10},
                "ventilation": {"humidity_based": True, "manual_lockout_min": 5}
            },
            "dashboard": {
                "title": "Test",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
        
        # Мигрируем манифест
        migrated = runner.migrate(old_manifest)
        
        # Валидируем с помощью Pydantic
        manifest = Manifest.model_validate(migrated)
        
        # Проверяем, что данные корректны
        assert manifest.version == 1
        assert len(manifest.devices) == 1
        assert manifest.devices[0].room == "living_room"
        assert manifest.devices[0].type == "light_motion"
