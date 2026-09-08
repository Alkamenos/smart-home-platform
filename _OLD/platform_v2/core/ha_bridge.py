#!/usr/bin/env python3
"""
HA Bridge V2 — мост между платформой и Home Assistant.

Отвечает за:
- Чтение состояний устройств из HA
- Применение команд к устройствам
- Подписку на изменения состояний
- Интеграцию с SyncEngine
"""
from typing import Callable, Optional
from OLD.platform_v2.core.sync_engine import SyncEngine

class HABridge:
    """
    Мост между платформой и Home Assistant.

    В реальном окружении использует:
    - hass.states.get() для чтения состояний
    - service.call() для применения команд
    - @state_trigger для подписки на изменения
    """

    def __init__(self, sync_engine: SyncEngine):
        self._sync = sync_engine
        self._state_reader: Optional[Callable] = None
        self._service_caller: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None

        # Подключаем SyncEngine к применению команд
        self._sync.set_apply_callback(self._apply_to_ha)

    def set_state_reader(self, reader: Callable[[str], Optional[str]]):
        """Установить функцию чтения состояний (в реальном окружении — hass.states.get)"""
        self._state_reader = reader

    def set_service_caller(self, caller: Callable[[str, str, dict], None]):
        """Установить функцию вызова сервисов (в реальном окружении — service.call)"""
        self._service_caller = caller

    def set_log_callback(self, callback: Callable[[str], None]):
        """Установить функцию логирования"""
        self._log_callback = callback

    # ===== Чтение состояний =====

    def get_state(self, entity_id: str) -> Optional[str]:
        """Прочитать состояние устройства из HA"""
        if self._state_reader:
            return self._state_reader(entity_id)
        return None

    def get_attribute(self, entity_id: str, attr: str) -> Optional[any]:
        """Прочитать атрибут устройства"""
        # В реальном окружении: hass.states.get(entity_id).attributes.get(attr)
        return None

    def get_float(self, entity_id: str) -> Optional[float]:
        """Прочитать числовое состояние"""
        state = self.get_state(entity_id)
        if state in (None, "unknown", "unavailable"):
            return None
        try:
            return float(state)
        except (ValueError, TypeError):
            return None

    # ===== Применение команд =====

    def _apply_to_ha(self, entity_id: str, state: str, attributes: dict):
        """Применить состояние к устройству в HA"""
        domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"

        if state == "off":
            self._call_service(domain, "turn_off", {"entity_id": entity_id})
        elif state == "on":
            service_data = {"entity_id": entity_id}
            service_data.update(attributes)
            self._call_service(domain, "turn_on", service_data)
        else:
            # Специфичные команды (например, climate.set_temperature)
            service_name = attributes.pop("service", "turn_on")
            service_data = {"entity_id": entity_id}
            service_data.update(attributes)
            self._call_service(domain, service_name, service_data)

    def _call_service(self, domain: str, service: str, data: dict):
        """Вызвать сервис в HA"""
        if self._service_caller:
            try:
                self._service_caller(domain, service, data)
                # Не логируем каждый вызов — только ошибки
            except Exception as e:
                self._log(f"[HA] Error calling {domain}.{service}: {e}")

    # ===== Синхронизация с SyncEngine =====

    def update_actual_states(self, entity_ids: list[str]):
        """Обновить реальные состояния устройств"""
        for entity_id in entity_ids:
            state = self.get_state(entity_id)
            if state:
                self._sync.update_actual(entity_id, state)

    def sync_tick(self) -> list[str]:
        """Запустить цикл синхронизации"""
        return self._sync.sync_tick()

    def _log(self, message: str):
        """Логирование"""
        if self._log_callback:
            self._log_callback(message)
        else:
            print(message)

# Глобальный экземпляр (инициализируется при запуске)
HA_BRIDGE = None

def init_ha_bridge(sync_engine: SyncEngine) -> HABridge:
    """Инициализировать мост к HA"""
    global HA_BRIDGE
    HA_BRIDGE = HABridge(sync_engine)
    return HA_BRIDGE
