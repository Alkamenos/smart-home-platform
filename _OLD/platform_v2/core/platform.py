#!/usr/bin/env python3
"""
Platform V2 — главный цикл платформы.

Отвечает за:
- Загрузку манифеста
- Инициализацию фич
- Запуск основного цикла
- Синхронизацию с HA
"""
import time
from typing import Optional
from OLD.platform_v2.core.manifest import load_manifest
from OLD.platform_v2.core.sync_engine import SyncEngine
from OLD.platform_v2.core.feature_base import REGISTRY
from OLD.platform_v2.core.feature_loader import load_features
from OLD.platform_v2.core.ha_bridge import HABridge, init_ha_bridge
from OLD.platform_v2.core.room_context import CONTEXT_BUILDER

class Platform:
    """Главный класс платформы"""

    def __init__(self, manifest_path: str):
        self._manifest_path = manifest_path
        self._manifest: Optional[dict] = None
        self._sync: Optional[SyncEngine] = None
        self._ha_bridge: Optional[HABridge] = None
        self._context_builder = CONTEXT_BUILDER
        self._running = False

        # Интервалы
        self._tick_interval = 30  # секунд
        self._sync_interval = 10  # секунд

    def initialize(self) -> bool:
        """Инициализация платформы"""
        try:
            # Загружаем манифест
            self._manifest = load_manifest(self._manifest_path)
            log.info(f"[PLATFORM V2] Manifest loaded: {self._manifest.get('instance_id')}")

            # Создаём движок синхронизации
            self._sync = SyncEngine(grace_sec=30)

            # Инициализируем мост к HA
            self._ha_bridge = init_ha_bridge(self._sync)

            # Загружаем фичи
            load_features(self._manifest, self._sync)

            feature_names = [f.feature_id for f in REGISTRY.get_all()]
            log.info(f"[PLATFORM V2] Features loaded: {feature_names}")

            return True
        except Exception as e:
            log.error(f"[PLATFORM V2] Initialization failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return False

    def start(self):
        """Запустить главный цикл"""
        if not self._manifest:
            if not self.initialize():
                return

        self._running = True
        log.info(f"[PLATFORM V2] Starting main loop...")

        last_tick = 0
        last_sync = 0

        while self._running:
            now = time.monotonic()

            # Основной цикл фич
            if now - last_tick >= self._tick_interval:
                self._tick()
                last_tick = now

            # Цикл синхронизации
            if now - last_sync >= self._sync_interval:
                self._sync_tick()
                last_sync = now

            task.sleep(1)

    def stop(self):
        """Остановить платформу"""
        self._running = False
        log.info("[PLATFORM V2] Stopped")

    def _tick(self):
        """Основной цикл фич"""
        # Строим контекст для каждой комнаты
        for room_id in self._manifest.get("rooms", []):
            room_config = self._get_room_config(room_id)
            room_context = self._context_builder.build(room_id, room_config)

            # Запускаем все фичи для этой комнаты
            REGISTRY.tick_all(room_context)

    def _sync_tick(self):
        """Цикл синхронизации"""
        if self._ha_bridge:
            # Обновляем реальные состояния
            all_entities = self._get_all_entities()
            self._ha_bridge.update_actual_states(all_entities)

            # Запускаем синхронизацию
            applied = self._ha_bridge.sync_tick()
            if applied:
                log.info(f"[PLATFORM V2] Synced {len(applied)} devices")

    def _get_room_config(self, room_id: str) -> dict:
        """Получить конфигурацию комнаты"""
        # Читаем сенсоры из манифеста
        config = {}

        for device in self._manifest.get("devices", {}).values():
            if device.get("room") != room_id:
                continue

            entity = device.get("entity", "")

            if "temperature" in entity or "temp" in entity:
                config["temp_sensor"] = entity
            elif "humidity" in entity or "vlazh" in entity:
                config["humidity_sensor"] = entity
            elif "motion" in entity:
                config["motion_sensor"] = entity
            elif "illuminance" in entity or "lux" in entity:
                config["illuminance_sensor"] = entity

        return config

    def _get_all_entities(self) -> list:
        """Получить все сущности для синхронизации"""
        entities = []
        for group in self._manifest.get("groups", {}).values():
            for device_id in group.get("devices", []):
                device = self._manifest.get("devices", {}).get(device_id)
                if device:
                    entities.append(device.get("entity"))
        return [e for e in entities if e]

    def get_status(self) -> dict:
        """Получить статус платформы"""
        return {
            "instance_id": self._manifest.get("instance_id") if self._manifest else None,
            "features": [f.feature_id for f in REGISTRY.get_all()],
            "rooms": self._manifest.get("rooms", []) if self._manifest else [],
            "sync_status": self._sync.get_status() if self._sync else {},
        }
