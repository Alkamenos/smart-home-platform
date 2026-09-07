#!/usr/bin/env python3
"""
Интеграция платформы V2 с Home Assistant.
"""
import sys
import os
from datetime import datetime

# Добавляем путь к платформе
platform_path = "/config/.platform"
if platform_path not in sys.path:
    sys.path.insert(0, platform_path)

log.info(f"[PLATFORM V2] sys.path: {sys.path[:3]}")

from platform_v2.core.manifest import load_manifest
from platform_v2.core.sync_engine import SyncEngine
from platform_v2.core.feature_base import REGISTRY
from platform_v2.core.feature_loader import load_features
from platform_v2.core.ha_bridge import HABridge
from platform_v2.core.room_context import RoomContextBuilder, CONTEXT_BUILDER

# ============================================================
# ИНИЦИАЛИЗАЦИЯ ПЛАТФОРМЫ
# ============================================================

MANIFEST_PATH = "/config/.platform/platform_v2/manifests/leonid_house.yaml"

def _platform_init():
    """Инициализация платформы"""
    log.info("[PLATFORM V2] Initializing...")
    
    try:
        # Загружаем манифест
        manifest = load_manifest(MANIFEST_PATH)
        log.info(f"[PLATFORM V2] Manifest loaded: {manifest.get('instance_id')}")
        
        # Создаём движок синхронизации
        sync_engine = SyncEngine(grace_sec=30)
        
        # Инициализируем мост к HA
        ha_bridge = HABridge(sync_engine)
        
        # Настраиваем чтение состояний
        def state_reader(entity_id):
            st = hass.states.get(entity_id)
            return st.state if st else None
        
        ha_bridge.set_state_reader(state_reader)
        
        # Настраиваем применение команд
        def service_caller(domain, service, data):
            service.call(domain, service, **data)
        
        ha_bridge.set_service_caller(service_caller)
        
        # Загружаем фичи
        load_features(manifest, sync_engine)
        feature_names = [f.feature_id for f in REGISTRY.get_all()]
        log.info(f"[PLATFORM V2] Features loaded: {feature_names}")
        
        # Настраиваем чтение времени
        import time
        CONTEXT_BUILDER.set_time_reader(time.localtime)
        
        # Генерируем дашборды (лениво, в отдельной функции)
        _generate_dashboards(manifest)
        
        # Создаём сенсор статуса
        try:
            feature_names = [f.feature_id for f in REGISTRY.get_all()]
            groups_count = len(manifest.get("groups", {}))
            state.set("sensor.platform_v2_status", "running",
                      instance_id=manifest.get("instance_id", ""),
                      rooms=str(manifest.get("rooms", [])),
                      features=str(feature_names),
                      groups_count=str(groups_count),
                      updated_at=str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            log.info("[PLATFORM V2] Status sensor created")
        except Exception as e:
            log.warning(f"[PLATFORM V2] Failed to create status sensor: {e}")
        
        # Создаём сенсоры состояний для каждой группы (для дашборда)
        try:
            for group_id in manifest.get("groups", {}):
                sensor_name = f"sensor.light_{group_id}_fsm_state"
                state.set(sensor_name, "OFF",
                          group_id=group_id,
                          updated_at=str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            # Создаём сенсоры для вентиляции
            for device_id, device in manifest.get("devices", {}).items():
                if device.get("capabilities", {}).get("fan"):
                    entity = device.get("entity", "")
                    sensor_name = entity.replace(".", "_") + "_fsm_state"
                    state.set(sensor_name, "NORMAL",
                              device_id=device_id,
                              updated_at=str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            log.info("[PLATFORM V2] FSM state sensors created")
        except Exception as e:
            log.warning(f"[PLATFORM V2] Failed to create FSM sensors: {e}")
        
        return manifest, sync_engine, ha_bridge
        
    except Exception as e:
        log.error(f"[PLATFORM V2] Initialization failed: {e}")
        import traceback
        log.error(traceback.format_exc())
        return None, None, None

def _generate_dashboards(manifest):
    """Генерация дашбордов (отдельно чтобы не блокировать импорт)"""
    try:
        from platform_v2.dashboards.generator import generate_all_dashboards
        generate_all_dashboards(manifest)
        log.info("[PLATFORM V2] Dashboards generated")
    except Exception as e:
        log.warning(f"[PLATFORM V2] Dashboard generation failed: {e}")

# ============================================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================================

_MANIFEST = None
_SYNC_ENGINE = None
_HA_BRIDGE = None
_ROOM_BUILDER = CONTEXT_BUILDER

@time_trigger("startup")
def platform_v2_loop():
    """Главный цикл платформы"""
    global _MANIFEST, _SYNC_ENGINE, _HA_BRIDGE
    
    # Инициализация
    _MANIFEST, _SYNC_ENGINE, _HA_BRIDGE = _platform_init()
    
    if not _MANIFEST:
        log.error("[PLATFORM V2] Failed to initialize")
        return
    
    log.info("[PLATFORM V2] Starting main loop...")
    
    tick_interval = 30  # секунд
    sync_interval = 2  # секунд (ускорено для теста)
    
    last_tick = 0
    last_sync = 0
    
    while True:
        import time
        now = time.monotonic()
        
        try:
            # Основной цикл фич
            if now - last_tick >= tick_interval:
                _platform_tick()
                last_tick = now
            
            # Цикл синхронизации
            if now - last_sync >= sync_interval:
                _platform_sync()
                last_sync = now
            
            task.sleep(1)
            
        except Exception as e:
            log.error(f"[PLATFORM V2] Loop error: {e}")
            task.sleep(5)

def _platform_tick():
    """Основной цикл фич"""
    if not _MANIFEST:
        return
    
    for room_id in _MANIFEST.get("rooms", []):
        # Строим контекст комнаты
        room_config = _get_room_config(room_id)
        room_context = _ROOM_BUILDER.build(room_id, room_config)
        
        # Запускаем все фичи
        REGISTRY.tick_all(room_context)
    
    # Обновляем сенсоры состояний для дашборда
    _update_fsm_state_sensors()

def _update_fsm_state_sensors():
    """Обновление сенсоров состояний для дашборда"""
    try:
        for group_id, group in _MANIFEST.get("groups", {}).items():
            sensor_name = f"sensor.light_{group_id}_fsm_state"
            
            # Получаем состояние из LightingFeature
            lighting_feature = None
            for f in REGISTRY.get_all():
                if f.feature_id == "lighting":
                    lighting_feature = f
                    break
            
            if lighting_feature:
                fsm_state = lighting_feature._fsm.get_state(f"light.{group_id}")
                if fsm_state:
                    state.set(sensor_name, fsm_state,
                              group_id=group_id,
                              updated_at=str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    except Exception:
        pass

def _platform_sync():
    """Цикл синхронизации (тихая версия без спама)"""
    if not _HA_BRIDGE or not _MANIFEST:
        return
    
    # Читаем реальные состояния из всех устройств манифеста
    read_count = 0
    error_count = 0
    all_devices = _MANIFEST.get("devices", {})
    
    for device_id, device in all_devices.items():
        entity_id = device.get("entity")
        if not entity_id:
            continue
        
        try:
            st = hass.states.get(entity_id)
            if st is None:
                continue
            
            state_val = str(st.state) if hasattr(st, "state") else str(st)
            
            if state_val in ("unknown", "unavailable", "None", ""):
                continue
            
            _SYNC_ENGINE.update_actual(entity_id, state_val)
            read_count += 1
        except Exception as e:
            error_count += 1
            # Логируем только ошибки чтения
            log.warning(f"[PLATFORM V2] Error reading {entity_id}: {e}")
    
    # Логируем только если есть ошибки или мало устройств прочитано
    if error_count > 0:
        log.warning(f"[PLATFORM V2] Read {read_count}/{len(all_devices)} entities, {error_count} errors")
    
    # Запускаем синхронизацию
    try:
        applied = _SYNC_ENGINE.sync_tick()
        # Логируем только если применили больше 2 устройств (иначе спам)
        if applied and len(applied) > 2:
            log.info(f"[PLATFORM V2] Applied {len(applied)} devices: {applied}")
    except Exception as e:
        log.warning(f"[PLATFORM V2] Sync tick error: {e}")

def _get_room_config(room_id: str) -> dict:
    """Получить конфигурацию комнаты"""
    config = {}
    
    for device in _MANIFEST.get("devices", {}).values():
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

# ============================================================
# СЕРВИСЫ ДЛЯ ДИАГНОСТИКИ
# ============================================================

@service
def platform_v2_status():
    """Статус платформы V2"""
    log.info(f"[PLATFORM V2] Status requested: manifest={_MANIFEST is not None}")
    
    if not _MANIFEST:
        return {"ok": False, "error": "Platform not initialized"}
    
    features_list = [f.feature_id for f in REGISTRY.get_all()]
    groups_list = list(_MANIFEST.get("groups", {}).keys())
    sync_status = _SYNC_ENGINE.get_status() if _SYNC_ENGINE else {}
    
    result = {
        "ok": True,
        "instance_id": _MANIFEST.get("instance_id"),
        "rooms": _MANIFEST.get("rooms", []),
        "features": features_list,
        "groups": groups_list,
        "groups_count": len(groups_list),
        "sync_status": sync_status,
    }
    
    log.info(f"[PLATFORM V2] Status: {result}")
    return result

@service
def platform_v2_restart():
    """Перезапуск платформы"""
    global _MANIFEST, _SYNC_ENGINE, _HA_BRIDGE
    
    log.info("[PLATFORM V2] Restarting...")
    
    _MANIFEST, _SYNC_ENGINE, _HA_BRIDGE = None, None, None
    _MANIFEST, _SYNC_ENGINE, _HA_BRIDGE = _platform_init()
    
    if _MANIFEST:
        log.info("[PLATFORM V2] Restarted successfully")
        return {"ok": True}
    else:
        return {"ok": False, "error": "Failed to restart"}

@service
def platform_v2_override_clear(entity: str = None):
    """Снять блокировки"""
    from platform_v2.core.override_manager import OVERRIDE
    
    if entity:
        OVERRIDE.release(entity)
        log.info(f"[PLATFORM V2] Override cleared: {entity}")
    else:
        OVERRIDE.release_all()
        log.info("[PLATFORM V2] All overrides cleared")
    
    return {"ok": True}

@service
def platform_v2_update_status_sensor():
    """Обновить сенсор статуса платформы"""
    if not _MANIFEST:
        log.warning("[PLATFORM V2] Status sensor: platform not initialized")
        return {"ok": False, "error": "Not initialized"}
    
    features_list = [f.feature_id for f in REGISTRY.get_all()]
    groups_list = list(_MANIFEST.get("groups", {}).keys())
    
    status_data = {
        "status": "running",
        "instance_id": _MANIFEST.get("instance_id"),
        "rooms": _MANIFEST.get("rooms", []),
        "features": features_list,
        "groups": groups_list,
        "groups_count": len(groups_list),
    }
    
    # Создаём сенсор статуса
    state.set("sensor.platform_v2_status", "running",
              instance_id=_MANIFEST.get("instance_id", ""),
              rooms=str(_MANIFEST.get("rooms", [])),
              features=str(features_list),
              groups_count=str(len(groups_list)),
              updated_at=str(time.strftime("%Y-%m-%d %H:%M:%S")))
    
    log.info(f"[PLATFORM V2] Status sensor updated")
    return {"ok": True, "status": status_data}

log.info("[PLATFORM V2] Integration module loaded")
