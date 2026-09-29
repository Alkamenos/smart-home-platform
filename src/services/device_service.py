"""
Сервис для управления устройствами.

Координирует синхронизацию, конфигурирование и управление состоянием устройств из Home Assistant.
Включает управление доступом на основе ролей пользователей.
Поддерживает кэширование списка устройств и индексирование для быстрого поиска.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Literal
from uuid import UUID

from src.core.events.event_bus import EventBus
from src.core.models.device import Device
from src.core.models.device_config import DeviceConfig
from src.core.models.device_access import DeviceAccess
from src.core.models.device_command import CommandExecutionResponse
from src.core.models.ha_source import HASource
from src.core.events.device_events import DeviceStateChangedEvent, DeviceConfigChangedEvent, DeviceAccessChangedEvent
from src.core.metrics import get_metrics_collector
from src.core.persistence.cache import DeviceCache
from src.core.persistence.index_manager import IndexManager

logger = logging.getLogger(__name__)


class DeviceService:
    """Сервис для управления устройствами и их синхронизацией."""

    def __init__(
        self,
        event_bus: EventBus,
        persistence_module: Optional[object] = None,
        ha_adapter: Optional[object] = None,
        cache_max_size: int = 1000,
        cache_ttl_seconds: int = 300,
    ) -> None:
        """Инициализация сервиса с зависимостями.

        Args:
            event_bus: Шина событий для публикации событий синхронизации
            persistence_module: Модуль персистентности для сохранения состояния
            ha_adapter: Адаптер Home Assistant для подключения и получения данных
            cache_max_size: Максимальный размер кэша (по умолчанию 1000)
            cache_ttl_seconds: TTL кэша в секундах (по умолчанию 300)
        """
        self.event_bus = event_bus
        self.persistence = persistence_module
        self.ha_adapter = ha_adapter
        self._devices: dict[UUID, Device] = {}
        self._sources: dict[UUID, HASource] = {}
        self._commands: dict[UUID, Dict[str, Any]] = {}  # Хранилище статусов команд
        self._unavailable_timers: dict[UUID, asyncio.Task] = {}  # Таймеры для отслеживания unavailable
        self._metrics = get_metrics_collector()  # Получить единый экземпляр метрик

        # Инициализация кэша и индекса
        self._cache = DeviceCache(max_size=cache_max_size, ttl_seconds=cache_ttl_seconds)
        self._index = IndexManager()

    async def sync_devices_from_source(self, source_id: UUID) -> list[Device]:
        """Синхронизирует устройства из указанного источника Home Assistant.

        Args:
            source_id: Идентификатор источника HA для синхронизации

        Returns:
            Список загруженных устройств

        Raises:
            ValueError: Если источник не найден
        """
        logger.info(f"Начинаю синхронизацию устройств из источника {source_id}")
        source_id_str = str(source_id)
        sync_start_time = time.time()

        try:
            # TODO: Реализовать получение устройств через HAAdapter
            # 1. Получить источник из persistence
            # 2. Подключиться к HA через ha_adapter
            # 3. Получить список устройств
            # 4. Преобразовать их в модели Device
            # 5. Сохранить в persistence
            # 6. Опубликовать события

            logger.info(f"Синхронизация из источника {source_id} завершена")

            # Записываем время синхронизации источника
            sync_duration = time.time() - sync_start_time
            self._metrics.record_source_sync_duration(source_id_str, sync_duration)

            return []

        except Exception as e:
            logger.error(f"Ошибка синхронизации источника {source_id}: {e}")
            # Записываем ошибку синхронизации
            error_type = type(e).__name__
            self._metrics.record_sync_error(source_id_str, error_type)
            raise

    async def get_device(self, device_id: UUID) -> Optional[Device]:
        """Получает устройство по ID с использованием кэша.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Модель устройства или None если не найдено
        """
        # Проверяем кэш
        cache_key = f"device:{device_id}"
        cached_device = self._cache.get(cache_key)
        if cached_device is not None:
            logger.debug(f"Устройство найдено в кэше: {device_id}")
            return cached_device

        # Если нет в кэше, проверяем индекс
        device = self._index.get_device(device_id)
        if device is None:
            device = self._devices.get(device_id)

        # Добавляем в кэш
        if device:
            self._cache.set(cache_key, device)
            logger.debug(f"Устройство добавлено в кэш: {device_id}")

        return device

    async def get_devices_by_source(self, source_id: UUID) -> list[Device]:
        """Получает все устройства из указанного источника с использованием индекса.

        Args:
            source_id: Идентификатор источника

        Returns:
            Список устройств от этого источника
        """
        # Проверяем кэш по префиксу источника
        cache_key = f"source:{source_id}"
        cached_devices = self._cache.get(cache_key)
        if cached_devices is not None:
            logger.debug(f"Устройства источника найдены в кэше: {source_id}")
            return cached_devices

        # Если нет в кэше, используем индекс
        devices = self._index.find_by_source(source_id)

        # Если в индексе нет, используем fallback
        if not devices:
            devices = [d for d in self._devices.values() if d.source_id == source_id]

        # Добавляем в кэш
        self._cache.set(cache_key, devices)
        logger.debug(f"Устройства источника добавлены в кэш: {source_id} (количество: {len(devices)})")

        return devices

    async def update_device_state(self, device_id: UUID, new_state: dict) -> None:
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

    def parse_devices(self, ha_states: list[dict]) -> list[Device]:
        """Преобразует состояния из Home Assistant в модели Device.

        Args:
            ha_states: Список состояний из HA (от /api/states)
            source_id: ID источника HA

        Returns:
            Список преобразованных Device объектов
        """
        devices = []

        for state_obj in ha_states:
            try:
                entity_id = state_obj.get("entity_id")
                if not entity_id:
                    continue

                # Извлекаем тип устройства из entity_id (e.g., "light" из "light.kitchen")
                domain = entity_id.split(".")[0]

                # Получаем атрибуты
                attributes = state_obj.get("attributes", {})
                friendly_name = attributes.get("friendly_name", entity_id)

                # Создаем Device модель
                device = Device(
                    ha_entity_id=entity_id,
                    source_id=UUID(int=0),  # Будет заполнено вызывающей функцией
                    name=friendly_name,
                    device_type=domain,
                    model=attributes.get("model"),
                    manufacturer=attributes.get("manufacturer"),
                    state={"state": state_obj.get("state")},
                    attributes=attributes,
                    status="available" if state_obj.get("state") != "unavailable" else "unavailable",
                )

                devices.append(device)
                logger.debug(f"Преобразовано устройство: {entity_id} -> {friendly_name}")

            except Exception as e:
                logger.warning(f"Ошибка преобразования состояния {state_obj}: {e}")
                continue

        logger.info(f"Преобразовано {len(devices)} устройств из HA")
        return devices

    # ============ T035-T042: Конфигурирование устройств (Фаза 4, US2) ============

    async def update_device_config(
        self,
        device_id: UUID,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        tags: Optional[list[str]] = None,
        updated_by: Optional[str] = None,
    ) -> DeviceConfig:
        """T036: Обновляет конфигурацию устройства.

        Валидирует и сохраняет конфигурацию устройства:
        - display_name: 1-255 символов, уникально
        - description: макс 1000 символов
        - location: макс 255 символов
        - tags: макс 10 тегов

        Args:
            device_id: ID устройства для обновления
            display_name: Новое пользовательское название
            description: Описание устройства
            location: Расположение устройства
            tags: Теги категоризации
            updated_by: Кто обновил конфигурацию (пользователь или система)

        Returns:
            Обновленная конфигурация устройства

        Raises:
            ValueError: Если устройство не найдено или валидация не пройдена
        """
        device = await self.get_device(device_id)
        if not device:
            raise ValueError(f"Устройство {device_id} не найдено")

        try:
            # Загружаем существующую конфигурацию или создаем новую
            from uuid import uuid4
            config = None
            if self.persistence:
                config = await self.persistence.load_device_config(device_id)

            if config is None:
                config = DeviceConfig(
                    device_id=device_id,
                    created_by=updated_by or "system",
                )
            else:
                config.updated_by = updated_by or "system"

            # Собираем измененные поля для события
            changed_fields = {}

            # Обновляем поля если они указаны
            if display_name is not None:
                changed_fields["display_name"] = {
                    "old": config.display_name,
                    "new": display_name,
                }
                config.display_name = display_name

            if description is not None:
                changed_fields["description"] = {
                    "old": config.description,
                    "new": description,
                }
                config.description = description

            if location is not None:
                changed_fields["location"] = {
                    "old": config.location,
                    "new": location,
                }
                config.location = location

            if tags is not None:
                changed_fields["tags"] = {
                    "old": config.tags,
                    "new": tags,
                }
                config.tags = tags

            config.updated_at = datetime.utcnow()

            # T037: Сохраняем конфигурацию в persistence
            if self.persistence:
                await self.persistence.save_device_config(config)
                logger.info(f"Конфигурация устройства {device_id} сохранена")

            # T040: Публикуем событие DeviceConfigChangedEvent
            self._publish_config_changed_event(
                device_id=device_id,
                changed_fields=changed_fields,
                changed_by=updated_by,
            )

            # T042: Обновляем конфигурацию в модели Device для сохранения при перезагрузке
            device.config = config.model_dump(mode="json")
            if self.persistence:
                await self.persistence.save_device(device)

            logger.info(f"Конфигурация устройства {device_id} обновлена: {changed_fields}")

            return config

        except ValueError as e:
            logger.error(f"Ошибка валидации при обновлении конфигурации устройства {device_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Ошибка обновления конфигурации устройства {device_id}: {e}")
            raise

    def _publish_config_changed_event(
        self,
        device_id: UUID,
        changed_fields: Dict[str, Any],
        changed_by: Optional[str] = None,
    ) -> None:
        """T040: Публикует событие изменения конфигурации через EventBus.

        Args:
            device_id: ID устройства
            changed_fields: Измененные поля
            changed_by: Кто сделал изменение
        """
        try:
            event = DeviceConfigChangedEvent(
                device_id=device_id,
                changed_fields=changed_fields,
                changed_by=changed_by or "unknown",
                timestamp=datetime.utcnow(),
            )

            # Публикуем событие
            self.event_bus.publish(event)
            logger.debug(f"Опубликовано событие изменения конфигурации для устройства {device_id}")

        except Exception as e:
            logger.error(f"Ошибка публикации события изменения конфигурации: {e}")

    def _publish_access_changed_event(
        self,
        device_id: UUID,
        user_id: str,
        action: str,
        role: Optional[str] = None,
        previous_role: Optional[str] = None,
        granted_by: Optional[str] = None,
    ) -> None:
        """T070: Публикует событие изменения доступа через EventBus.

        Args:
            device_id: ID устройства
            user_id: ID пользователя
            action: Действие (granted, revoked, updated)
            role: Новая роль (при granted/updated)
            previous_role: Предыдущая роль
            granted_by: Администратор который совершил действие
        """
        try:
            event = DeviceAccessChangedEvent(
                device_id=device_id,
                user_id=user_id,
                action=action,
                role=role,
                previous_role=previous_role,
                granted_by=granted_by,
                timestamp=datetime.utcnow(),
            )

            # Публикуем событие
            self.event_bus.publish(event)
            logger.debug(
                f"Опубликовано событие изменения доступа: {action} для user {user_id} на device {device_id}"
            )

        except Exception as e:
            logger.error(f"Ошибка публикации события изменения доступа: {e}")

    # T066: Методы проверки и управления доступом

    async def check_device_access(
        self, device_id: UUID, user_id: str, required_role: Literal["viewer", "controller", "admin"] = "viewer"
    ) -> bool:
        """Проверяет имеет ли пользователь доступ к устройству с требуемой ролью.

        Args:
            device_id: Идентификатор устройства
            user_id: Идентификатор пользователя
            required_role: Требуемая роль (viewer, controller, admin)

        Returns:
            True если пользователь имеет доступ, False иначе
        """
        try:
            # Получаем запись доступа из persistence
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.warning("Persistence модуль не имеет device_access")
                return False

            access = await self.persistence.device_access.load_access_for_user_device(
                device_id, user_id
            )

            if not access:
                logger.debug(f"Доступ не найден для user {user_id} -> device {device_id}")
                return False

            # Проверяем что роль достаточно для требуемого действия
            role_hierarchy = {"viewer": 0, "controller": 1, "admin": 2}
            user_level = role_hierarchy.get(access.role, -1)
            required_level = role_hierarchy.get(required_role, -1)

            if user_level >= required_level:
                logger.debug(
                    f"Доступ разрешен: user {user_id} имеет роль {access.role} для device {device_id}"
                )
                return True

            logger.debug(
                f"Доступ запрещен: user {user_id} имеет роль {access.role}, требуется {required_role}"
            )
            return False

        except Exception as e:
            logger.error(f"Ошибка проверки доступа: {e}")
            return False

    async def grant_access(
        self, device_id: UUID, user_id: str, role: Literal["viewer", "controller", "admin"], granted_by: str
    ) -> Optional[DeviceAccess]:
        """Предоставляет пользователю доступ к устройству.

        Args:
            device_id: Идентификатор устройства
            user_id: Идентификатор пользователя
            role: Роль пользователя (viewer, controller, admin)
            granted_by: ID пользователя (администратора) который предоставляет доступ

        Returns:
            Созданная запись доступа или None если ошибка
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.error("Persistence модуль не имеет device_access")
                return None

            # Проверяем что пользователь грантер является админом
            # (эту проверку должен делать route handler)

            # Проверяем что устройство существует
            device = await self.get_device(device_id)
            if not device:
                logger.warning(f"Устройство {device_id} не найдено")
                return None

            # Проверяем что роль валидна
            if role not in ["viewer", "controller", "admin"]:
                logger.warning(f"Невалидная роль: {role}")
                return None

            # Проверяем существует ли уже доступ (для определения действия)
            previous_access = await self.persistence.device_access.load_access_for_user_device(device_id, user_id)
            previous_role = previous_access.role if previous_access else None

            # Удаляем существующий доступ если есть
            if previous_access:
                await self.persistence.device_access.delete_access(previous_access.id)

            # Создаем новую запись доступа
            access = DeviceAccess(
                device_id=device_id,
                user_id=user_id,
                role=role,
                granted_by=granted_by
            )

            # Сохраняем в persistence
            await self.persistence.device_access.save_access(access)

            # T070: Публикуем событие изменения доступа
            action = "updated" if previous_role else "granted"
            self._publish_access_changed_event(
                device_id=device_id,
                user_id=user_id,
                action=action,
                role=role,
                previous_role=previous_role,
                granted_by=granted_by,
            )

            logger.info(
                f"Доступ предоставлен: user {user_id} роль {role} для device {device_id} (грантер: {granted_by})"
            )

            return access

        except Exception as e:
            logger.error(f"Ошибка предоставления доступа: {e}")
            return None

    async def revoke_access(self, access_id: UUID) -> bool:
        """Отзывает доступ пользователя к устройству.

        Args:
            access_id: Идентификатор записи доступа для удаления

        Returns:
            True если удалено успешно
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.error("Persistence модуль не имеет device_access")
                return False

            # Получаем запись доступа перед удалением (для события)
            access = await self.persistence.device_access.load_access(access_id)

            result = await self.persistence.device_access.delete_access(access_id)

            if result and access:
                # T070: Публикуем событие отзыва доступа
                self._publish_access_changed_event(
                    device_id=access.device_id,
                    user_id=access.user_id,
                    action="revoked",
                    previous_role=access.role,
                    granted_by=None,
                )
                logger.info(f"Доступ {access_id} отозван")

            return result

        except Exception as e:
            logger.error(f"Ошибка отзыва доступа: {e}")
            return False

    async def get_device_accesses(self, device_id: UUID) -> list[DeviceAccess]:
        """Получает список всех доступов к устройству.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Список записей доступа
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.warning("Persistence модуль не имеет device_access")
                return []

            return await self.persistence.device_access.load_accesses_for_device(device_id)

        except Exception as e:
            logger.error(f"Ошибка получения доступов к устройству {device_id}: {e}")
            return []

    async def get_user_accessible_devices(self, user_id: str) -> list[Device]:
        """Получает все устройства, к которым пользователь имеет доступ.

        Args:
            user_id: Идентификатор пользователя

        Returns:
            Список устройств с доступом
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.warning("Persistence модуль не имеет device_access")
                return []

            # Получаем все записи доступа пользователя
            user_accesses = await self.persistence.device_access.load_accesses_for_user(user_id)

            # Получаем устройства с доступом
            devices = []
            for access in user_accesses:
                device = await self.get_device(access.device_id)
                if device:
                    devices.append(device)

            logger.debug(f"Пользователь {user_id} имеет доступ к {len(devices)} устройствам")
            return devices

        except Exception as e:
            logger.error(f"Ошибка получения доступных устройств пользователя {user_id}: {e}")
            return []

    # ============ T049-T052: WebSocket синхронизация состояния ============

    async def handle_state_change(self, event_data: Dict[str, Any]) -> None:
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

            old_state = event_data.get("data", {}).get("old_state")
            new_state_data = event_data.get("data", {}).get("new_state", {})

            # Обновляем состояние устройства
            old_state_dict = device.state.copy()
            device.state = {
                "state": new_state_data.get("state"),
                **new_state_data.get("attributes", {})
            }
            device.last_state_update = datetime.utcnow()

            # Если устройство было unavailable, переводим его в available
            if device.status == "unavailable" and device.state.get("state") != "unavailable":
                device.status = "available"
                self._cancel_unavailable_timer(device.id)

            logger.info(f"Updated state for device {device.id} ({entity_id})")

            # T058: Публикуем событие через EventBus
            self._publish_state_changed_event(
                device_id=device.id,
                old_state=old_state_dict,
                new_state=device.state,
            )

            # T060: Обновляем таймер доступности
            self._reset_unavailable_timer(device.id)

        except Exception as e:
            logger.error(f"Error handling state change: {e}")

    def _cancel_unavailable_timer(self, device_id: UUID) -> None:
        """Отменяет таймер недоступности для устройства."""
        if device_id in self._unavailable_timers:
            self._unavailable_timers[device_id].cancel()
            del self._unavailable_timers[device_id]

    def _reset_unavailable_timer(self, device_id: UUID) -> None:
        """T060: Сбрасывает таймер на отслеживание недоступности (60 сек)."""
        # Отменяем старый таймер если существует
        self._cancel_unavailable_timer(device_id)

        # Создаем новый таймер
        async def mark_unavailable():
            await asyncio.sleep(60)
            device = await self.get_device(device_id)
            if device and device.status == "available":
                device.status = "unavailable"
                logger.warning(
                    f"Device {device_id} marked as unavailable after 60 seconds without update"
                )
                # Обновляем метрики доступности
                self._update_device_availability_metrics()
                # Публикуем событие об изменении статуса
                self._publish_state_changed_event(
                    device_id=device_id,
                    old_state={"status": "available"},
                    new_state={"status": "unavailable"},
                )

        task = asyncio.create_task(mark_unavailable())
        self._unavailable_timers[device_id] = task

    # ============ T053-T057: Отправка команд и отслеживание статуса ============

    async def execute_command(
        self,
        device_id: UUID,
        command_name: str,
        parameters: Dict[str, Any],
        timeout: int = 30,
    ) -> CommandExecutionResponse:
        """T053: Отправляет команду на выполнение в Home Assistant.

        Args:
            device_id: ID устройства
            command_name: Имя команды
            parameters: Параметры команды
            timeout: Таймаут выполнения в секундах (макс 300)

        Returns:
            Объект с информацией о выполненной команде

        Raises:
            ValueError: Если устройство не найдено
            RuntimeError: Если команда не выполнена
        """
        device = await self.get_device(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        if timeout > 300:
            timeout = 300

        try:
            command_id = UUID(int=1)  # Будет заполнено уникальным ID
            from uuid import uuid4
            command_id = uuid4()

            # Устройство для метрик
            device_type = device.device_type or "unknown"
            source_id_str = str(device.source_id)

            # Записываем отправку команды
            self._metrics.record_command_sent(source_id_str, device_type, command_name)

            # Создаем запись о команде
            command_record = {
                "id": command_id,
                "device_id": device_id,
                "command_name": command_name,
                "parameters": parameters,
                "status": "executing",
                "created_at": datetime.utcnow(),
                "completed_at": None,
                "result": None,
                "error": None,
            }

            # Сохраняем запись о команде
            self._commands[command_id] = command_record

            logger.info(
                f"Executing command {command_name} on device {device_id} "
                f"with parameters {parameters}"
            )

            # Отправляем команду в HA через адаптер
            if not self.ha_adapter:
                raise RuntimeError("HA adapter not configured")

            # T055: Асинхронное выполнение команды с таймаутом
            try:
                result = await asyncio.wait_for(
                    self._call_ha_service(device, command_name, parameters),
                    timeout=timeout,
                )

                command_record["status"] = "success"
                command_record["result"] = result
                command_record["completed_at"] = datetime.utcnow()

                # Записываем успех команды
                self._metrics.record_command_success(source_id_str, device_type, command_name)

                logger.info(
                    f"Command {command_name} succeeded on device {device_id}: {result}"
                )

            except asyncio.TimeoutError:
                command_record["status"] = "failed"
                command_record["error"] = f"Command timeout after {timeout} seconds"
                command_record["completed_at"] = datetime.utcnow()

                # Записываем ошибку команды
                self._metrics.record_command_failed(source_id_str, device_type, command_name, "timeout")

                logger.error(
                    f"Command {command_name} timeout on device {device_id}"
                )
                # T059: Публикуем ошибку
                raise RuntimeError(command_record["error"])

            except Exception as e:
                command_record["status"] = "failed"
                command_record["error"] = str(e)
                command_record["completed_at"] = datetime.utcnow()

                # Записываем ошибку команды
                error_type = type(e).__name__
                self._metrics.record_command_failed(source_id_str, device_type, command_name, error_type)

                logger.error(
                    f"Command {command_name} failed on device {device_id}: {e}"
                )
                # T059: Публикуем ошибку
                raise RuntimeError(command_record["error"])

            # Возвращаем ответ
            return CommandExecutionResponse(
                id=command_id,
                device_id=device_id,
                command_name=command_name,
                status=command_record["status"],
                created_at=command_record["created_at"],
                completed_at=command_record["completed_at"],
                result=command_record["result"],
                error=command_record["error"],
            )

        except Exception as e:
            logger.error(f"Error executing command: {e}")
            raise

    async def _call_ha_service(
        self,
        device: Device,
        command_name: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Вызывает сервис в Home Assistant.

        Args:
            device: Объект устройства
            command_name: Имя команды
            parameters: Параметры

        Returns:
            Результат выполнения сервиса
        """
        if not self.ha_adapter:
            raise RuntimeError("HA adapter not configured")

        # Формируем domain.service из команды
        domain = device.device_type  # e.g., "light"
        service = command_name  # e.g., "turn_on"

        # Вызываем через адаптер
        result = await self.ha_adapter.call_service(
            domain=domain,
            service=service,
            entity_id=device.ha_entity_id,
            **parameters
        )

        return result or {}

    async def get_command_status(
        self,
        device_id: UUID,
        command_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """T055/T056: Получает статус выполненной команды.

        Args:
            device_id: ID устройства
            command_id: ID команды

        Returns:
            Информация о команде или None если не найдена
        """
        command = self._commands.get(command_id)
        if not command or command["device_id"] != device_id:
            return None

        return command

    # ============ T058: События ============

    def _publish_state_changed_event(
        self,
        device_id: UUID,
        old_state: Optional[Dict[str, Any]],
        new_state: Dict[str, Any],
    ) -> None:
        """T058: Публикует событие изменения состояния через EventBus.

        Args:
            device_id: ID устройства
            old_state: Старое состояние
            new_state: Новое состояние
        """
        try:
            event = DeviceStateChangedEvent(
                device_id=device_id,
                old_state=old_state,
                new_state=new_state,
                timestamp=datetime.utcnow(),
                source="ha",
            )

            # Публикуем событие
            self.event_bus.publish(event)
            logger.debug(f"Published state changed event for device {device_id}")

        except Exception as e:
            logger.error(f"Error publishing state changed event: {e}")

    # ============ Методы управления кэшем и индексом ============

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Получить статистику кэша.

        Returns:
            Словарь со статистикой кэша
        """
        return self._cache.get_stats()

    def get_index_stats(self) -> Dict[str, Any]:
        """
        Получить статистику индекса.

        Returns:
            Словарь со статистикой индекса
        """
        return self._index.get_stats()

    def clear_cache(self) -> None:
        """Очистить весь кэш."""
        self._cache.clear()
        logger.info("Кэш устройств очищен")

    def invalidate_device_cache(self, device_id: UUID) -> bool:
        """
        Инвалидировать кэш для конкретного устройства.

        Args:
            device_id: ID устройства

        Returns:
            True если элемент был удален из кэша
        """
        device = self._devices.get(device_id)
        result = self._cache.invalidate(f"device:{device_id}")

        if device:
            self._cache.invalidate(f"source:{device.source_id}")

        return result

    def invalidate_source_cache(self, source_id: UUID) -> int:
        """
        Инвалидировать кэш для всех устройств источника.

        Args:
            source_id: ID источника

        Returns:
            Количество инвалидированных элементов
        """
        count = self._cache.invalidate_by_prefix(f"source:{source_id}")
        logger.info(f"Кэш источника инвалидирован: {source_id} ({count} элементов)")
        return count

    def rebuild_index(self) -> None:
        """Пересоздать индекс из всех устройств в памяти."""
        devices = list(self._devices.values())
        self._index.rebuild_from_devices(devices)
        logger.info(f"Индекс пересоздан: {len(devices)} устройств")

    def add_devices_to_cache_and_index(self, devices: list[Device]) -> None:
        """
        Добавить устройства в кэш и индекс.

        Args:
            devices: Список устройств для добавления
        """
        for device in devices:
            self._devices[device.id] = device
            self._index.add_device(device)

        logger.info(f"Добавлено {len(devices)} устройств в кэш и индекс")

    def find_devices_by_type(self, device_type: str) -> list[Device]:
        """
        Найти все устройства по типу с использованием индекса.

        Args:
            device_type: Тип устройства (light, switch, binary_sensor, etc.)

        Returns:
            Список устройств
        """
        return self._index.find_by_type(device_type)

    def find_device_by_ha_entity_id(self, ha_entity_id: str) -> Optional[Device]:
        """
        Найти устройство по HA entity ID.

        Args:
            ha_entity_id: HA entity ID (e.g., 'light.kitchen_light')

        Returns:
            Устройство или None если не найдено
        """
        device = self._index.find_by_ha_entity_id(ha_entity_id)
        if device:
            # Добавить в кэш
            self._cache.set(f"device:{device.id}", device)
        return device


    # ============ Prometheus Metrics Helper Methods ============

    def _update_device_availability_metrics(self) -> None:
        """Обновляет метрики доступности устройств по источникам и типам.

        Анализирует состояние всех устройств и обновляет gauge метрики
        для отслеживания количества доступных/недоступных устройств.
        """
        try:
            # Группируем устройства по (source_id, device_type)
            device_counts: dict[tuple[str, str], tuple[int, int]] = {}

            for device in self._devices.values():
                source_id_str = str(device.source_id)
                device_type = device.device_type or "unknown"
                key = (source_id_str, device_type)

                if key not in device_counts:
                    device_counts[key] = (0, 0)

                available, unavailable = device_counts[key]

                if device.status == "available":
                    available += 1
                else:
                    unavailable += 1

                device_counts[key] = (available, unavailable)

            # Обновляем метрики для каждой комбинации source_id и device_type
            for (source_id_str, device_type), (available, unavailable) in device_counts.items():
                self._metrics.set_devices_available(source_id_str, device_type, available)
                self._metrics.set_devices_unavailable(source_id_str, device_type, unavailable)

            logger.debug(f"Обновлены метрики доступности устройств: {device_counts}")

        except Exception as e:
            logger.error(f"Ошибка при обновлении метрик доступности: {e}")

    def update_sources_connected_count(self, count: int) -> None:
        """Обновляет метрику количества подключенных источников.

        Args:
            count: Количество подключенных источников
        """
        try:
            self._metrics.set_sources_connected_count(count)
            logger.debug(f"Обновлена метрика подключенных источников: {count}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении метрики источников: {e}")

    def update_cache_metrics(self, cache_size_bytes: int) -> None:
        """Обновляет метрики кэша.

        Args:
            cache_size_bytes: Размер кэша в байтах
        """
        try:
            self._metrics.set_cache_size(cache_size_bytes)
            logger.debug(f"Обновлена метрика размера кэша: {cache_size_bytes} bytes")
        except Exception as e:
            logger.error(f"Ошибка при обновлении метрик кэша: {e}")

    def record_cache_hit(self, cache_type: str = "device") -> None:
        """Записывает попадание в кэш.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        try:
            self._metrics.record_cache_hit(cache_type)
        except Exception as e:
            logger.error(f"Ошибка при записи cache hit: {e}")

    def record_cache_miss(self, cache_type: str = "device") -> None:
        """Записывает промах кэша.

        Args:
            cache_type: Тип кэша (например, "device", "config")
        """
        try:
            self._metrics.record_cache_miss(cache_type)
        except Exception as e:
            logger.error(f"Ошибка при записи cache miss: {e}")
