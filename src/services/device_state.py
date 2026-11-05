"""Device state synchronization for the device service (spec 018, T058).

Extracted from DeviceService: applying Home Assistant states and availability is
a synchronization concern, separate from device storage and command execution.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID


logger = logging.getLogger("services.device_service")

#: ????????? ???????, ?????????? ??? ?????????. ?? ?????? ??? Home Assistant:
#: ?????????? ?????? (`unavailable`) ? ??????, ???????? ???????? ??? ??
#: ????????? (`unknown`). ???????? ??????? ???? ?? ?????????: ?????? ??
#: ????????? ? ?? ????????????? (BACKLOG B70).
UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})


class DeviceStateMixin:
    """Apply source states and availability to known devices."""

    async def apply_source_states(self, states: list[dict[str, Any]]) -> int:
        """Привести состояния известных устройств к источнику истины (B62).

        Состояние устройства — следствие Home Assistant, а не собственность
        снимка из хранилища: после перезапуска `devices.json` отдаёт состояние на
        момент последней записи (у штор — 5 октября), и платформа показывает
        вчерашний день, пока сущность не сменит состояние сама. Синхронизация по
        кнопке это лечила, но нажимать её после каждого перезапуска никто не
        обязан.

        Args:
            states: Состояния из Home Assistant (`get_states` либо `/api/states`).

        Returns:
            Сколько устройств изменило состояние.
        """
        by_entity = {device.ha_entity_id: device for device in self._devices.values()}
        updated = 0
        for raw in states:
            entity_id = raw.get("entity_id")
            if not entity_id:
                continue
            device = self._index.find_by_ha_entity_id(entity_id) or by_entity.get(entity_id)
            if device is None:
                continue
            new_state = {
                "state": raw.get("state"),
                **(raw.get("attributes") or {}),
            }
            if device.state != new_state:
                device.state = new_state
                updated += 1
            device.last_state_update = datetime.utcnow()
            self._apply_availability(device)
        if updated:
            logger.info(f"Состояния устройств обновлены из Home Assistant: {updated}")
        return updated

    async def handle_state_change(self, event_data: dict[str, Any]) -> None:
        """T050: Обрабатывает изменение состояния устройства из WebSocket.

        Args:
            event_data: Данные события изменения состояния из HA
        """
        try:
            entity_id = event_data.get("data", {}).get("entity_id")
            if not entity_id:
                logger.warning("Event data missing entity_id")
                return

            # Найти устройство по entity_id
            device = None
            for dev in self._devices.values():
                if dev.ha_entity_id == entity_id:
                    device = dev
                    break

            if not device:
                logger.debug(f"Device not found for entity_id: {entity_id}")
                return

            event_data.get("data", {}).get("old_state")
            new_state_data = event_data.get("data", {}).get("new_state", {})

            # Обновляем состояние устройства
            old_state_dict = device.state.copy()
            device.state = {
                "state": new_state_data.get("state"),
                **new_state_data.get("attributes", {}),
            }
            device.last_state_update = datetime.utcnow()

            # Доступность — по состоянию прибора, а не по молчанию. Home Assistant
            # сам помечает потерянный прибор (`unavailable`) и восстановленный
            # (`unknown` — значение ещё не прочитано); «давно не менялось» — это не
            # недоступность: лампа, которая просто горит, молчит, и объявлять её
            # сломанной значит врать в интерфейсе (боевой случай 2026-10-14:
            # «Свет над столом: прибор недоступен» при включённой лампе).
            self._apply_availability(device)

            logger.info(f"Updated state for device {device.id} ({entity_id})")

            # T058: Публикуем событие через EventBus
            await self._publish_state_changed_event(
                device_id=device.id,
                old_state=old_state_dict,
                new_state=device.state,
            )

        except Exception as e:
            logger.error(f"Error handling state change: {e}")

    def _apply_availability(self, device: Any) -> None:
        """Привести статус доступности устройства к состоянию прибора.

        Args:
            device: Устройство сервиса.

        Returns:
            Ничего.
        """
        raw = (device.state or {}).get("state")
        status = "unavailable" if str(raw).lower() in UNAVAILABLE_STATES else "available"
        if device.status != status:
            device.status = status
            self._update_device_availability_metrics()

    # ============ T053-T057: Отправка команд и отслеживание статуса ============
    async def update_device_state(self, device_id: UUID, new_state: dict[str, Any]) -> None:
        """Обновляет состояние устройства и инвалидирует кэш.

        Args:
            device_id: Идентификатор устройства
            new_state: Новое состояние
        """
        device = self._devices.get(device_id)
        if device:
            device.state = new_state
            logger.info(f"Обновлено состояние устройства {device_id}: {new_state}")

            # Инвалидировать кэш при обновлении состояния
            self._cache.invalidate(f"device:{device_id}")
            self._cache.invalidate(f"source:{device.source_id}")
            logger.debug(f"Кэш инвалидирован для устройства: {device_id}")

            # Обновляем метрики доступности
            self._update_device_availability_metrics()
