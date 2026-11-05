"""
Сервис для управления устройствами.

Координирует синхронизацию, конфигурирование и управление состоянием устройств из Home Assistant.
Включает управление доступом на основе ролей пользователей.
Поддерживает кэширование списка устройств и индексирование для быстрого поиска.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from core.events.event_bus import EventBus
from core.metrics import get_metrics_collector
from core.models.device import Device
from core.models.device_config import DeviceConfig
from core.models.ha_source import HASource
from core.persistence.cache import DeviceCache
from core.persistence.index_manager import IndexManager
from services.device_access import DeviceAccessMixin
from services.device_cache import DeviceCacheMixin
from services.device_commands import DeviceCommandMixin
from services.device_events import DeviceEventsMixin
from services.device_state import DeviceStateMixin
from services.source_sync import SourceSynchronizer, sync_filter_enabled as sync_filter_enabled


logger = logging.getLogger(__name__)

EVENT_DEVICE_LOADED = "device.loaded"
EVENT_DEVICE_CONFIG_CHANGED = "device.config_changed"
EVENT_DEVICE_STATE_CHANGED = "device.state_changed"
EVENT_DEVICE_ACCESS_CHANGED = "device.access_changed"
EVENT_DEVICE_REMOVED = "device.removed"

#: Состояния прибора, означающие «не отвечает». Их ставит сам Home Assistant:
#: потерянный прибор (`unavailable`) и прибор, значение которого ещё не
#: прочитано (`unknown`). Молчание прибора сюда не относится: «давно не
#: менялось» — не недоступность (BACKLOG B70).
UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})

# Канал Home Assistant с изменениями состояния. Раньше обработчик
# handle_state_change существовал, но ни на что не подписывался, поэтому
# состояние устройства обновлялось только синхронизацией (FR-007).
EVENT_HA_STATE_CHANGE = "state_change"


class DeviceService(
    DeviceAccessMixin,
    DeviceCommandMixin,
    DeviceEventsMixin,
    DeviceCacheMixin,
    DeviceStateMixin,
):
    """Сервис для управления устройствами и их синхронизацией."""

    def __init__(
        self,
        event_bus: EventBus,
        persistence_module: object | None = None,
        ha_adapter: object | None = None,
        cache_max_size: int = 1000,
        cache_ttl_seconds: int = 300,
        engine: object | None = None,
        event_router: object | None = None,
        manifest: object | None = None,
    ) -> None:
        """Инициализация сервиса с зависимостями.

        Args:
            event_bus: Шина событий для публикации событий синхронизации
            persistence_module: Модуль персистентности для сохранения состояния
            ha_adapter: Адаптер Home Assistant для подключения и получения данных
            cache_max_size: Максимальный размер кэша (по умолчанию 1000)
            cache_ttl_seconds: TTL кэша в секундах (по умолчанию 300)
            engine: Движок машин состояний — нужен, чтобы снимать автоматику
                устройств, исчезнувших из Home Assistant (spec 006, FR-016).
            event_router: Маршрутизатор событий — перестраивается после снятия.
            manifest: Манифест платформы — нужен только при включённом
                `SYNC_FILTER_MANIFEST_ONLY`, чтобы синхронизация забирала
                состояния описанных сущностей и уже известных сервису (см.
                `sync_entity_filter`). `None` оставляет синхронизацию без
                фильтра, что верно для сборок без манифеста.
        """
        self.event_bus = event_bus
        # Четыре зависимости ниже — «утиные» объекты без общего протокола:
        # персистентность (модуль/менеджер), HA-адаптер, движок машин состояний
        # и маршрутизатор событий. Они подставляются контейнером и в тестах
        # (MagicMock/None), поэтому типизируем их как Any: аннотация object
        # ломала бы любой доступ к атрибутам (attr-defined), а Protocol здесь
        # невыгоден — HAAdapter.call_service принимает **kwargs и через
        # Protocol не проходит структурную проверку.
        self.persistence: Any = persistence_module
        self.ha_adapter: Any = ha_adapter
        self._engine: Any = engine
        self._event_router: Any = event_router
        self._manifest: Any = manifest
        self._devices: dict[UUID, Device] = {}
        self._sources: dict[UUID, HASource] = {}
        # Удалённые устройства: по ним отличаем «уже удалено» от «неизвестно»,
        # поэтому повторный DELETE идемпотентен, а неизвестный id даёт 404
        # (spec 006, FR-025/FR-027).
        self._deleted_devices: set[UUID] = set()
        self._commands: dict[UUID, dict[str, Any]] = {}  # Хранилище статусов команд
        self._metrics = get_metrics_collector()  # Получить единый экземпляр метрик

        # Инициализация кэша и индекса
        self._cache = DeviceCache(max_size=cache_max_size, ttl_seconds=cache_ttl_seconds)
        self._index = IndexManager()
        self._state_change_subscribed = False
        # Синхронизация вынесена в отдельный класс (B80): сервис остаётся
        # единственным входом и владельцем хранилища.
        self._sync = SourceSynchronizer(self)

    def subscribe_state_changes(self) -> None:
        """Подписать обработчик изменения состояния устройства на шину.

        Подписка выполняется ровно один раз: повторный вызов (например, при
        пересборке приложения) не создаёт дубликатов, иначе одно событие
        Home Assistant обрабатывалось бы несколько раз (FR-007).
        """
        if self._state_change_subscribed:
            logger.debug("Device state change subscription already registered")
            return

        self.event_bus.subscribe(EVENT_HA_STATE_CHANGE, self._on_ha_state_change_event)
        self._state_change_subscribed = True
        logger.debug(f"Subscribed to {EVENT_HA_STATE_CHANGE} for device state updates")

    async def _on_ha_state_change_event(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Привести событие шины к формату Home Assistant и обработать его.

        Args:
            event_type: Имя события.
            payload: Полезная нагрузка события изменения состояния.
            trace_id: Идентификатор трассы.
        """
        entity_id = (payload or {}).get("entity_id")
        if not entity_id:
            return

        await self.handle_state_change(
            {
                "data": {
                    "entity_id": entity_id,
                    "old_state": payload.get("old_state"),
                    "new_state": {"state": payload.get("new_state")},
                }
            }
        )

    async def sync_devices_from_source(self, source_id: UUID) -> list[Device]:
        """Синхронизирует устройства из указанного источника Home Assistant.

        Сам путь синхронизации живёт в `SourceSynchronizer` (B80): здесь —
        публичный вход сервиса. Показатели доступности обновляются после успеха,
        потому что считаются по хранилищу сервиса.

        Args:
            source_id: Идентификатор источника HA для синхронизации.

        Returns:
            Список загруженных устройств.

        Raises:
            ValueError: Если источник не найден.
        """
        devices = await self._sync.run(source_id)
        self._update_device_availability_metrics()
        return devices

    def sync_entity_filter(self, source_id: UUID) -> set[str] | None:
        """Сущности, состояния которых синхронизация должна принимать.

        Ответ живёт в `SourceSynchronizer`; метод сохранён как часть контракта
        сервиса (его проверяет `tests/unit/test_sync_entity_filter.py`).

        Args:
            source_id: Идентификатор источника.

        Returns:
            Множество допустимых `ha_entity_id` либо None, если фильтр не
            применяется.
        """
        return self._sync.entity_filter(source_id)

    async def get_device(self, device_id: UUID) -> Device | None:
        """Получает устройство по ID с использованием кэша.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Модель устройства или None если не найдено
        """
        # Проверяем кэш
        cache_key = f"device:{device_id}"
        cached_device: Device | None = self._cache.get(cache_key)
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

    async def get_all_devices(self) -> list[Device]:
        """Возвращает все известные устройства (единый источник, FR-003).

        Returns:
            Список устройств, зарегистрированных в сервисе.
        """
        return list(self._devices.values())

    async def list_devices(self, source_id: UUID | None = None) -> list[Device]:
        """Возвращает список устройств с необязательной фильтрацией по источнику.

        Args:
            source_id: Идентификатор источника; None — все устройства.

        Returns:
            Список устройств.
        """
        devices = await self.get_all_devices()
        if source_id is None:
            return devices
        return [device for device in devices if device.source_id == source_id]

    async def hydrate_from_persistence(self) -> int:
        """Загружает устройства из постоянного хранилища в память сервиса.

        Вызывается один раз при создании приложения: без этого список устройств
        был пуст до первой синхронизации, а добавленные устройства исчезали
        после перезапуска (FR-004, D-002).

        Returns:
            Количество загруженных устройств.
        """
        if self.persistence is None or not hasattr(self.persistence, "devices"):
            logger.warning("Persistence недоступен: гидратация устройств пропущена")
            return 0

        try:
            devices = await self.persistence.devices.load_all_devices()
        except Exception as e:
            logger.error(f"Не удалось загрузить устройства из хранилища: {e}")
            return 0

        for device in devices:
            self._devices[device.id] = device
            self._index.add_device(device)
            self._cache.set(f"device:{device.id}", device)

        if devices:
            logger.info(f"Гидратировано устройств из хранилища: {len(devices)}")
        return len(devices)

    def _find_by_entity_id(self, ha_entity_id: str, source_id: UUID) -> Device | None:
        """Ищет устройство по идентификатору сущности в пределах источника.

        Args:
            ha_entity_id: Идентификатор сущности Home Assistant.
            source_id: Идентификатор источника.

        Returns:
            Найденное устройство или None.
        """
        found = self._index.find_by_ha_entity_id(ha_entity_id)
        if found is not None and found.source_id == source_id:
            return found
        for device in self._devices.values():
            if device.ha_entity_id == ha_entity_id and device.source_id == source_id:
                return device
        return None

    async def add_device(self, device: Device) -> Device:
        """Добавляет устройство в постоянное хранилище и в память сервиса.

        Повторное добавление устройства с тем же идентификатором сущности в
        пределах источника обновляет существующую запись (сохраняются её id и
        время создания) вместо создания дубликата (FR-008).

        Args:
            device: Устройство для добавления.

        Returns:
            Сохранённое устройство.

        Raises:
            RuntimeError: Если постоянное хранилище недоступно.
        """
        if self.persistence is None or not hasattr(self.persistence, "devices"):
            msg = "Persistence недоступен: устройство не может быть сохранено"
            raise RuntimeError(msg)

        existing = self._devices.get(device.id) or self._find_by_entity_id(
            device.ha_entity_id, device.source_id
        )
        if existing is not None and existing.id != device.id:
            device = device.model_copy(
                update={"id": existing.id, "created_at": existing.created_at}
            )

        await self.persistence.devices.save_device(device)

        if device.id in self._devices:
            self._index.update_device(device)
        else:
            self._index.add_device(device)
        self._devices[device.id] = device
        self._cache.set(f"device:{device.id}", device)
        self._invalidate_source_cache(device.source_id)

        logger.info(f"Устройство сохранено: {device.ha_entity_id} (источник {device.source_id})")
        return device

    def was_device_deleted(self, device_id: UUID) -> bool:
        """Сообщает, удалялось ли устройство за время работы процесса.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            True, если устройство уже удалялось.
        """
        return device_id in self._deleted_devices

    async def remove_device(self, device_id: UUID) -> bool:
        """Удаляет устройство из постоянного хранилища, индекса и кэша.

        Идемпотентно: удаление отсутствующего устройства возвращает False
        (FR-025, FR-027). Снятие машин состояний выполняет сервис жизненного
        цикла — здесь только данные и индексы.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            True, если устройство было удалено; False, если его не было.
        """
        device = self._devices.get(device_id) or self._index.get_device(device_id)
        if device is None:
            return False

        if self.persistence is not None and hasattr(self.persistence, "devices"):
            await self.persistence.devices.delete_device(device_id)
        await self.persistence.device_access.delete_accesses_for_device(device_id)
        self._deleted_devices.add(device_id)

        self._index.remove_device(device_id)
        self._devices.pop(device_id, None)
        self._cache.invalidate(f"device:{device_id}")
        self._invalidate_source_cache(device.source_id)

        logger.info(f"Устройство удалено: {device.ha_entity_id}")
        return True

    def _invalidate_source_cache(self, source_id: UUID) -> None:
        """Сбрасывает кэш выборки источника после изменения состава устройств.

        Args:
            source_id: Идентификатор источника.
        """
        if self.persistence is not None and hasattr(self.persistence, "sources"):
            self.invalidate_source_cache(source_id)

    async def get_devices_by_source(self, source_id: UUID) -> list[Device]:
        """Получает все устройства из указанного источника с использованием индекса.

        Args:
            source_id: Идентификатор источника

        Returns:
            Список устройств от этого источника
        """
        # Проверяем кэш по префиксу источника
        cache_key = f"source:{source_id}"
        cached_devices: list[Device] | None = self._cache.get(cache_key)
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
        logger.debug(
            f"Устройства источника добавлены в кэш: {source_id} (количество: {len(devices)})"
        )

        return devices

    def parse_devices(self, ha_states: list[dict[str, Any]]) -> list[Device]:
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
                    status="available"
                    if state_obj.get("state") != "unavailable"
                    else "unavailable",
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
        display_name: str | None = None,
        description: str | None = None,
        location: str | None = None,
        tags: list[str] | None = None,
        updated_by: str | None = None,
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
            await self._publish_config_changed_event(
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
            logger.error(
                f"Ошибка валидации при обновлении конфигурации устройства {device_id}: {e}"
            )
            raise
        except Exception as e:
            logger.error(f"Ошибка обновления конфигурации устройства {device_id}: {e}")
            raise
