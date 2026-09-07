#!/usr/bin/env python3
"""Тесты для Блока 4: Интеграция с HA, Дашборды, Платформа"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
import yaml
from platform_v2.core.manifest import load_manifest, Manifest
from platform_v2.core.sync_engine import SyncEngine
from platform_v2.core.ha_bridge import HABridge, init_ha_bridge
from platform_v2.dashboards.generator import DashboardGenerator

def create_test_manifest():
    """Создать тестовый манифест"""
    return Manifest(
        instance_id="test_house",
        rooms=["living_room", "bedroom"],
        devices={
            "light_living": type("Device", (), {
                "id": "light_living",
                "entity_id": "light.living_room",
                "name": "Свет гостиной",
                "room": "living_room",
                "capabilities": {"dim": True},
                "managed_by_platform": True
            })(),
        },
        groups={
            "living_room_lights": type("Group", (), {
                "id": "living_room_lights",
                "name": "Свет гостиной",
                "room": "living_room",
                "devices": ["light_living"],
                "fsm": None,
                "features": {"motion": {"enabled": True}}
            })(),
        },
        features={
            "lighting": type("Feature", (), {
                "name": "lighting",
                "enabled": True,
                "config": {},
                "flags": {}
            })(),
        },
        global_flags={
            "winter": "input_boolean.zima",
            "night": "input_boolean.vecher",
        }
    )

class TestHABridge:
    def test_init_bridge(self):
        """Инициализация моста"""
        sync = SyncEngine()
        bridge = HABridge(sync)
        
        assert bridge is not None
    
    def test_apply_state_to_ha(self):
        """Применение состояния к устройству"""
        applied = []
        
        def mock_service_caller(domain, service, data):
            applied.append((domain, service, data))
        
        sync = SyncEngine()
        bridge = HABridge(sync)
        bridge.set_service_caller(mock_service_caller)
        
        # Устанавливаем желаемое состояние
        sync.set_desired("light.test", "on", attributes={"brightness_pct": 80})
        
        # Применяем
        bridge._apply_to_ha("light.test", "on", {"brightness_pct": 80})
        
        assert len(applied) == 1
        assert applied[0][0] == "light"
        assert applied[0][1] == "turn_on"
        assert applied[0][2]["brightness_pct"] == 80
    
    def test_sync_with_ha(self):
        """Синхронизация с HA"""
        sync = SyncEngine(grace_sec=0)
        bridge = HABridge(sync)
        
        # Мокаем чтение состояний
        states = {"light.test": "off"}
        bridge.set_state_reader(lambda e: states.get(e))
        
        # Устанавливаем желаемое
        sync.set_desired("light.test", "on")
        
        # Обновляем реальное состояние
        bridge.update_actual_states(["light.test"])
        
        # Проверяем расхождение
        divergences = sync.get_divergences()
        assert len(divergences) == 1

class TestDashboardGenerator:
    def test_generate_home_dashboard(self):
        """Генерация главного дашборда"""
        manifest = create_test_manifest()
        generator = DashboardGenerator(manifest)
        
        dashboard = generator.generate_home_dashboard()
        
        assert dashboard["title"] == "Дом"
        assert len(dashboard["views"]) == 2  # living_room и bedroom
    
    def test_generate_settings_dashboard(self):
        """Генерация дашборда настроек"""
        manifest = create_test_manifest()
        generator = DashboardGenerator(manifest)
        
        dashboard = generator.generate_settings_dashboard()
        
        assert dashboard["title"] == "Настройки"
        assert len(dashboard["views"]) >= 1
    
    def test_room_cards_generated(self):
        """Проверка генерации карточек комнаты"""
        manifest = create_test_manifest()
        generator = DashboardGenerator(manifest)
        
        dashboard = generator.generate_home_dashboard()
        
        # Находим комнату
        living_room_view = next(v for v in dashboard["views"] if v["path"] == "living_room")
        assert len(living_room_view["cards"]) > 0
    
    def test_save_dashboard_to_yaml(self):
        """Сохранение дашборда в YAML"""
        manifest = create_test_manifest()
        generator = DashboardGenerator(manifest)
        
        dashboard = generator.generate_home_dashboard()
        
        # Сохраняем во временный файл
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            generator.save_dashboard(dashboard, f.name)
            temp_path = f.name
        
        # Проверяем что файл валидный
        with open(temp_path) as f:
            loaded = yaml.safe_load(f)
        
        assert loaded["title"] == "Дом"
        os.unlink(temp_path)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
