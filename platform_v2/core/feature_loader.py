#!/usr/bin/env python3
"""
Feature Loader V2 — загрузка фич из манифеста.

Создаёт экземпляры фич на основе конфигурации манифеста.
"""
from typing import Optional
from platform_v2.core.sync_engine import SyncEngine
from platform_v2.core.feature_base import FeatureBase, REGISTRY
from platform_v2.features.lighting import LightingFeature
from platform_v2.features.ventilation import VentilationFeature

class FeatureLoader:
    """Загрузчик фич из манифеста"""
    
    def __init__(self, sync_engine: SyncEngine):
        self._sync = sync_engine
    
    def load_from_manifest(self, manifest: dict) -> None:
        """Загрузить все фичи из манифеста"""
        features = manifest.get("features", {})
        
        # Освещение
        if "lighting" in features and features["lighting"].get("enabled", True):
            lighting_config = dict(features["lighting"].get("config", {}))
            
            # Преобразуем группы: заменяем строковые device_id на реальные устройства
            groups = {}
            manifest_devices = manifest.get("devices", {})
            
            for group_id, group in manifest.get("groups", {}).items():
                new_group = dict(group)
                # Заменяем строковые id устройств на полные объекты
                new_devices = []
                for dev_id in group.get("devices", []):
                    if isinstance(dev_id, str) and dev_id in manifest_devices:
                        new_devices.append(manifest_devices[dev_id])
                    elif isinstance(dev_id, dict):
                        new_devices.append(dev_id)
                new_group["devices"] = new_devices
                groups[group_id] = new_group
            
            lighting_config["groups"] = groups
            lighting = LightingFeature(lighting_config, self._sync)
            REGISTRY.register(lighting)
        
        # Вентиляция
        if "ventilation" in features and features["ventilation"].get("enabled", True):
            ventilation_config = dict(features["ventilation"].get("config", {}))
            # Добавляем устройства вентиляции из манифеста
            ventilation_config["devices"] = [
                {"entity": d["entity"], "name": d["name"]}
                for d in manifest.get("devices", {}).values()
                if d.get("capabilities", {}).get("fan")
            ]
            ventilation = VentilationFeature(ventilation_config, self._sync)
            REGISTRY.register(ventilation)

def load_features(manifest: dict, sync_engine: SyncEngine) -> None:
    """Удобная функция загрузки фич"""
    loader = FeatureLoader(sync_engine)
    loader.load_from_manifest(manifest)
