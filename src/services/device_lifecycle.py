"""
Сервис жизненного цикла устройства (spec 006, D-003).

Единственная точка, выполняющая операцию над устройством целиком:

    манифест → постоянное хранилище → runtime (кэш/индекс)
    → машины состояний → карта маршрутизации → аудит

Слой сервисов: зависит только от ядра (``core``) и от переданных внедрённых
зависимостей; не импортирует ``adapters`` и ``webui`` (конституция IV).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.core.models.device import Device
from src.core.models.device_sync_event import DeviceSyncEvent
from src.core.models.manifest import BehaviorConfig, DeviceConfig, RoomConfig


if TYPE_CHECKING:
    from src.core.events.event_router import EventRouter
    from src.core.fsm.engine import FSMEngine
    from src.core.fsm.factory import FSMFactory
    from src.core.models.manifest import Manifest
    from src.core.persistence.manager import PersistenceManager
    from src.services.device_service import DeviceService


DEFAULT_USER_ID = "admin_user"
"""Инициатор операции по умолчанию, если вызывающий не указал пользователя."""


class DeviceLifecycleService:
    """Транзакции жизненного цикла устройств: добавление, изменение, снятие.

    Класс не владеет манифестом и компонентами ядра — они передаются при
    создании. Это позволяет использовать сервис и в веб-приложении, и в
    автономном режиме без движка машин состояний.

    Attributes:
        manifest: Актуальный манифест (состав дома).
        device_service: Сервис устройств (кэш, индекс, постоянное хранилище).
        factory: Фабрика машин состояний; None в автономном режиме.
        engine: Движок машин состояний; None в автономном режиме.
        event_router: Маршрутизатор событий; None в автономном режиме.
        persistence: Менеджер хранения для аудита.
    """

    def __init__(
        self,
        manifest: Manifest,
        device_service: DeviceService,
        factory: FSMFactory | None = None,
        engine: FSMEngine | None = None,
        event_router: EventRouter | None = None,
        persistence: PersistenceManager | None = None,
    ) -> None:
        """Создаёт сервис жизненного цикла.

        Args:
            manifest: Актуальный манифест.
            device_service: Сервис устройств.
            factory: Фабрика машин состояний.
            engine: Движок машин состояний.
            event_router: Маршрутизатор событий.
            persistence: Менеджер хранения (аудит).
        """
        self.manifest = manifest
        self.device_service = device_service
        self.factory = factory
        self.engine = engine
        self.event_router = event_router
        self.persistence = persistence or device_service.persistence

    # ============ Добавление и изменение ============

    async def add_device(
        self,
        device: Device,
        room_id: str,
        behaviors: list[BehaviorConfig] | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> tuple[Device, bool]:
        """Добавляет устройство и оживляет его без перезапуска.

        Порядок операций (D-012): манифест → постоянное хранилище → runtime →
        машины состояний → маршрутизация → аудит. Сбой записи в хранилище
        откатывает манифест; сбой на шаге машин состояний сохраняет данные и
        фиксируется частичным успехом.

        Args:
            device: Устройство для добавления.
            room_id: Комната, в которую помещается устройство.
            behaviors: Поведения устройства; None — берутся из манифеста.
            user_id: Инициатор операции для аудита.

        Returns:
            Кортеж ``(устройство, True)``, если устройство создано, и
            ``(устройство, False)``, если обновлено существующее (FR-008).

        Raises:
            ValueError: Если комната не найдена в манифесте.
            RuntimeError: Если не удалось сохранить устройство.
        """
        room = self._require_room(room_id)
        if device.name == "":
            device.name = device.ha_entity_id

        behaviors = behaviors or self._behaviors_from_manifest(room, device.ha_entity_id)
        snapshot = copy.deepcopy(room)

        # Существующее устройство определяется по идентификатору сущности:
        # при выборе из мастера каждый раз создаётся новый UUID (FR-008)
        existing = self.device_service.find_device_by_ha_entity_id(device.ha_entity_id)
        if existing is not None and existing.source_id == device.source_id:
            device = device.model_copy(
                update={"id": existing.id, "created_at": existing.created_at}
            )
        created = existing is None

        self._upsert_manifest_entry(room, device, behaviors)
        self._rebuild_manifest_device(room, device, behaviors)

        try:
            await self.device_service.add_device(device)
        except Exception as e:
            self._restore_room(room, snapshot)
            msg = f"Не удалось сохранить устройство в постоянном хранилище: {e}"
            raise RuntimeError(msg) from e

        await self._ensure_user_access(device, user_id)
        fsm_error = await self._safe_sync_fsm(room, device, behaviors)
        self._rebuild_event_routing()

        await self._record_audit(
            device_id=device.id,
            action="device_added" if created else "device_updated",
            user_id=user_id,
            after=self._snapshot(device, behaviors),
            data={"fsm_error": fsm_error} if fsm_error else None,
        )
        logger.info(
            f"Устройство {'добавлено' if created else 'обновлено'} и оживлено: "
            f"{device.ha_entity_id} (комната {room_id})"
        )
        return device, created

    async def update_device(
        self,
        device: Device,
        room_id: str,
        behaviors: list[BehaviorConfig],
        user_id: str = DEFAULT_USER_ID,
    ) -> Device:
        """Обновляет устройство и пересобирает его машины состояний.

        Args:
            device: Устройство.
            room_id: Комната устройства.
            behaviors: Новый состав поведений.
            user_id: Инициатор операции для аудита.

        Returns:
            Сохранённое устройство.

        Raises:
            ValueError: Если комната не найдена в манифесте.
            RuntimeError: Если не удалось сохранить устройство.
        """
        room = self._require_room(room_id)
        before = self._snapshot(device, self._behaviors_from_manifest(room, device.ha_entity_id))

        self._upsert_manifest_entry(room, device, behaviors)
        self._rebuild_manifest_device(room, device, behaviors)

        try:
            await self.device_service.add_device(device)
        except Exception as e:
            msg = f"Не удалось сохранить устройство в постоянном хранилище: {e}"
            raise RuntimeError(msg) from e

        fsm_error = await self._safe_sync_fsm(room, device, behaviors)
        self._rebuild_event_routing()

        await self._record_audit(
            device_id=device.id,
            action="device_updated",
            user_id=user_id,
            before=before,
            after=self._snapshot(device, behaviors),
            data={"fsm_error": fsm_error} if fsm_error else None,
        )
        logger.info(f"Устройство обновлено: {device.ha_entity_id}")
        return device

    async def deactivate_device(self, device: Device, user_id: str = DEFAULT_USER_ID) -> None:
        """Снимает активную автоматику устройства, сохраняя его данные.

        Используется при переводе устройства в статус ``removed_from_ha``:
        конфигурация и права сохраняются, но события больше не приводят к
        командам (FR-022).

        Args:
            device: Устройство, автоматику которого нужно снять.
            user_id: Инициатор операции для аудита.
        """
        if self.engine is not None:
            for entity_id in self.engine.get_entities_by_device(device.ha_entity_id):
                self.engine.unregister(entity_id)
        self._rebuild_event_routing()

        await self._record_audit(
            device_id=device.id,
            action="device_archived",
            user_id=user_id,
            data={"ha_entity_id": device.ha_entity_id},
        )
        logger.info(f"Автоматика устройства снята: {device.ha_entity_id}")

    # ============ Машины состояний ============

    async def _ensure_user_access(self, device: Device, user_id: str) -> None:
        """Выдаёт инициатору права администратора на добавленное устройство.

        Без этого устройство не попадало бы в список: список отдаёт только
        устройства, доступные пользователю (SC-001). Права выдаются по той же
        схеме device-blind, что и остальные выдачи (specs/004).

        Args:
            device: Добавленное устройство.
            user_id: Инициатор операции.
        """
        if user_id == "system":
            return
        persistence = self.persistence
        if persistence is None or not hasattr(persistence, "device_access"):
            return

        try:
            accesses = await self.device_service.get_device_accesses(device.id)
            if any(access.user_id == user_id for access in accesses):
                return
            await self.device_service.grant_access(
                device_id=device.id, user_id=user_id, role="admin", granted_by=user_id
            )
        except Exception as e:
            logger.warning(f"Не удалось выдать права на {device.ha_entity_id} для {user_id}: {e}")

    async def _safe_sync_fsm(
        self, room: RoomConfig, device: Device, behaviors: list[BehaviorConfig]
    ) -> str | None:
        """Синхронизирует автоматики устройства, не теряя данные при сбое.

        По D-012 сбой на шаге машин состояний не откатывает сохранённые данные:
        устройство остаётся в манифесте и в хранилище, а ошибка возвращается
        для фиксации в аудите.

        Args:
            room: Комната устройства.
            device: Устройство.
            behaviors: Актуальные поведения.

        Returns:
            Текст ошибки или None при успехе.
        """
        try:
            await self._sync_fsm_for_device(room, device, behaviors)
        except Exception as e:
            logger.error(f"Не удалось создать автоматику для {device.ha_entity_id}: {e}")
            return str(e)
        return None

    async def _sync_fsm_for_device(
        self, room: RoomConfig, device: Device, behaviors: list[BehaviorConfig]
    ) -> None:
        """Создаёт автоматики устройства по актуальному составу поведений.

        Используются только публичные API движка: определения создаются фабрикой,
        перед регистрацией старая автоматика снимается, чтобы не осталось
        дублей и устаревших таймеров (D-004).

        Args:
            room: Комната устройства.
            device: Устройство.
            behaviors: Актуальные поведения.
        """
        if self.factory is None or self.engine is None:
            logger.info(f"Фабрика машин состояний недоступна: {device.ha_entity_id} без автоматики")
            return

        for entity_id in self.engine.get_entities_by_device(device.ha_entity_id):
            self.engine.unregister(entity_id)

        for behavior in behaviors:
            definitions = self.factory.create_from_behavior(device.ha_entity_id, behavior)
            for definition in definitions:
                # restore_state=False: состояние пересоздаётся, а не берётся
                # из persistence (иначе ветка восстановления вне event loop падает)
                self.engine.register_definition(definition, restore_state=False)

    def _rebuild_event_routing(self) -> None:
        """Перестраивает карту «датчик → автоматика» (FR-015)."""
        if self.event_router is not None:
            self.event_router.rebuild(self.manifest)

    # ============ Манифест ============

    def _require_room(self, room_id: str) -> RoomConfig:
        """Находит комнату манифеста.

        Args:
            room_id: Идентификатор комнаты.

        Returns:
            Модель комнаты.

        Raises:
            ValueError: Если комната не найдена.
        """
        for room in self.manifest.rooms:
            if room.id == room_id:
                return room
        msg = f"Комната '{room_id}' не найдена в манифесте"
        raise ValueError(msg)

    @staticmethod
    def _behaviors_from_manifest(room: RoomConfig, ha_entity_id: str) -> list[BehaviorConfig]:
        """Возвращает поведения устройства из манифеста.

        Args:
            room: Комната устройства.
            ha_entity_id: Идентификатор устройства.

        Returns:
            Список поведений (пустой, если устройства нет в манифесте).
        """
        for device in room.devices:
            if device.id == ha_entity_id:
                return list(device.behaviors)
        return []

    @staticmethod
    def _upsert_manifest_entry(
        room: RoomConfig, device: Device, behaviors: list[BehaviorConfig]
    ) -> None:
        """Создаёт или обновляет запись устройства в комнате (идемпотентно).

        Args:
            room: Комната устройства.
            device: Устройство.
            behaviors: Поведения устройства.
        """
        entry = DeviceConfig(
            id=device.ha_entity_id,
            type=device.device_type,
            name=device.name,
            behaviors=[BehaviorConfig(**b.model_dump()) for b in behaviors],
        )
        for index, existing in enumerate(room.devices):
            if existing.id == device.ha_entity_id:
                room.devices[index] = entry
                return
        room.devices.append(entry)

    @staticmethod
    def _rebuild_manifest_device(
        room: RoomConfig, device: Device, behaviors: list[BehaviorConfig]
    ) -> DeviceConfig:
        """Возвращает актуальную запись устройства в комнате.

        Args:
            room: Комната устройства.
            device: Устройство.
            behaviors: Поведения устройства.

        Returns:
            Модель устройства манифеста.
        """
        for entry in room.devices:
            if entry.id == device.ha_entity_id:
                entry.type = device.device_type
                entry.name = device.name
                entry.behaviors = [BehaviorConfig(**b.model_dump()) for b in behaviors]
                return entry
        return DeviceConfig(id=device.ha_entity_id, type=device.device_type, name=device.name)

    @staticmethod
    def _restore_room(room: RoomConfig, snapshot: RoomConfig) -> None:
        """Восстанавливает состояние комнаты из снимка (компенсация).

        Args:
            room: Комната для восстановления.
            snapshot: Снимок состояния до операции.
        """
        room.devices = list(snapshot.devices)
        room.sensors = dict(snapshot.sensors)

    # ============ Аудит ============

    async def _record_audit(
        self,
        device_id: Any,
        action: str,
        user_id: str = DEFAULT_USER_ID,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Записывает операцию в журнал (FR-028).

        Ошибка журналирования не приводит к потере результата операции:
        она фиксируется предупреждением (D-012).

        Args:
            device_id: Устройство операции; None для действий уровня источника.
            action: Тип операции.
            user_id: Инициатор операции.
            before: Снимок до изменения.
            after: Снимок после изменения.
            data: Дополнительные данные.
        """
        if self.persistence is None or not hasattr(self.persistence, "device_sync_events"):
            return

        event = DeviceSyncEvent(
            device_id=device_id,
            action=action,  # type: ignore[arg-type]
            user_id=user_id,
            before=before,
            after=after,
            data=data,
        )
        try:
            await self.persistence.device_sync_events.append_event(event)
        except Exception as e:
            logger.warning(f"Не удалось записать событие аудита '{action}': {e}")

    @staticmethod
    def _snapshot(device: Device, behaviors: list[BehaviorConfig]) -> dict[str, Any]:
        """Формирует снимок состояния устройства для аудита.

        Args:
            device: Устройство.
            behaviors: Поведения устройства.

        Returns:
            Словарь значимых полей.
        """
        return {
            "ha_entity_id": device.ha_entity_id,
            "device_type": device.device_type,
            "name": device.name,
            "behaviors": [b.model_dump() for b in behaviors],
        }
