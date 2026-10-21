"""Синхронизация устройств из источника Home Assistant (B80).

Здесь весь путь синхронизации: прочитать состояния, свести их с известными,
записать результат, снять автоматику исчезнувших и обновить источник. Раньше это
лежало в `DeviceService` — один класс на 1859 строк. Зависимость от сервиса не
спрятана: протокол `SyncHost` перечисляет нужные внутренности и проверяется mypy.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from core.logger import get_logger
from core.models.device import Device
from core.models.ha_source import HASource


#: Журнал синхронизации источника (B87): отдельный логгер компонента, потому что
#: INFO корневого логгера в контейнере не виден (урок #70), а ход и итог
#: синхронизации должны быть видны без перевода успеха в предупреждение.
_sync_logger = get_logger("source_sync")

#: Переменная окружения, включающая фильтр сущностей при синхронизации.
SYNC_FILTER_ENV = "SYNC_FILTER_MANIFEST_ONLY"

#: Значения, читаемые как «включено». Незаданная переменная — «выключено».
_TRUTHY_VALUES = {"1", "true", "yes", "on"}

#: Пользователь, которому выдаются права на новые устройства синхронизации.
SYNC_ACCESS_USER = "admin_user"


def sync_filter_enabled() -> bool:
    """Включён ли фильтр сущностей при синхронизации.

    По умолчанию **выключен**, и это решение владельца, а не техническая
    осторожность. Фильтр меняет контракт платформы: при нём синхронизация
    перестаёт быть способом узнать о новом устройстве и остаётся только
    обновлением уже описанного — добавить устройство может мастер discovery.

    Цена измерена, а не предположена: включение фильтра роняет **38 тестов**,
    из них 21 в `tests/integration/{test_device_sync,test_device_sync_lifecycle,
    test_concurrency_and_removal}.py` и 17 контрактных и прочих. Это не
    устаревшие тесты — они проверяют нынешний контракт как рабочий, и переписывание
    их под новое поведение означало бы смену контракта без отдельного на то
    решения.

    Поэтому флаг по умолчанию `false`: как и `SHADOW_MODE`, забытая настройка не
    должна молча менять смысл платформы. Включать осознанно, и тогда падение
    тестов — это список меняющихся поведений, а не сбой.

    Returns:
        True, если фильтр применять.
    """
    return os.environ.get(SYNC_FILTER_ENV, "").strip().lower() in _TRUTHY_VALUES


class SyncHost(Protocol):
    """Внутренности сервиса устройств, которые нужны синхронизации.

    Протокол — не попытка сделать синхронизацию независимой: она часть
    `DeviceService` и работает с его хранилищем, индексом и движком. Протокол
    делает эту связь видимой и проверяемой: если сервис перестанет отдавать
    что-то из перечисленного, ошибка будет на этапе проверки типов, а не в бою.
    """

    persistence: Any
    _devices: dict[UUID, Device]
    _index: Any
    _engine: Any
    _event_router: Any
    _manifest: Any
    _metrics: Any

    def parse_devices(self, ha_states: list[dict[str, Any]]) -> list[Device]:
        """Преобразовать состояния Home Assistant в модели устройств."""
        ...

    async def grant_access(
        self,
        device_id: UUID,
        user_id: str,
        role: Literal["viewer", "controller", "admin"],
        granted_by: str,
    ) -> Any:
        """Выдать права на устройство."""
        ...

    async def _publish_device_loaded_event(self, device: Device) -> None:
        """Опубликовать событие загрузки устройства."""
        ...

    async def _publish_device_removed_event(self, device: Device) -> None:
        """Опубликовать событие исчезновения устройства."""
        ...


class SourceSynchronizer:
    """Синхронизация устройств из источника Home Assistant.

    Args:
        host: Сервис устройств — хранилище, индекс, движок, маршрутизатор,
            манифест и метрики берутся у него.
    """

    def __init__(self, host: SyncHost) -> None:
        """Запомнить сервис, в хранилище которого пишется результат.

        Args:
            host: Сервис устройств.
        """
        self._host = host

    async def run(self, source_id: UUID) -> list[Device]:
        """Синхронизировать устройства из указанного источника Home Assistant.

        Args:
            source_id: Идентификатор источника HA для синхронизации.

        Returns:
            Список загруженных устройств.

        Raises:
            ValueError: Если источник не найден.
        """
        _sync_logger.info(f"Начинаю синхронизацию устройств из источника {source_id}")
        source_id_str = str(source_id)
        sync_start_time = time.time()

        try:
            # 1. Получить источник из persistence
            if not self._host.persistence or not hasattr(self._host.persistence, "sources"):
                raise ValueError("Persistence модуль не имеет sources")

            source = await self._host.persistence.sources.load_source(source_id)
            if not source:
                raise ValueError(f"Источник {source_id} не найден")

            _sync_logger.info(f"Источник найден: {source.name} ({source.url})")

            # 2-4. Прочитать состояния источника через REST-клиент
            parsed_devices = await self._fetch(source, source_id)

            # 5. Свести результат с единым хранилищем: обновить известные
            # устройства, создать новые, пометить исчезнувшие. Раньше каждая
            # синхронизация порождала новые записи с новыми id (дубли), а
            # исчезнувшие устройства навсегда оставались обычными (spec 006).
            merged, removed = await self._merge(source_id, parsed_devices)

            # 6-9. Записать результат: хранилище → память и индекс → снятие
            # автоматики исчезнувших → события
            await self._persist_result(merged, removed)

            # 10. Обновить источник: время последней синхронизации, состояние и число
            # устройств. Без состояния источник остаётся «отключённым» при
            # успешной синхронизации, и интерфейс показывает неправду.
            await self._mark_synced(source, device_count=len(merged))

            # 11. Обновляем метрики
            sync_duration = time.time() - sync_start_time
            self._host._metrics.record_source_sync_duration(source_id_str, sync_duration)

            _sync_logger.info(
                f"Синхронизация из источника {source_id} успешно завершена: "
                f"устройств в источнике — {len(merged)}, исчезнувших — {len(removed)}, "
                f"время — {sync_duration:.2f}s"
            )

            return merged

        except Exception as e:
            _sync_logger.error(f"Ошибка синхронизации источника {source_id}: {e}")
            # Записываем ошибку синхронизации
            error_type = type(e).__name__
            self._host._metrics.record_sync_error(source_id_str, error_type)

            # Обновляем источник: он переходит в «отключён», иначе интерфейс
            # покажет работающее соединение при сломанном. Время последней
            # успешной синхронизации при этом не меняется — иначе расхождение
            # между датой и данными не было бы видно.
            try:
                if self._host.persistence and hasattr(self._host.persistence, "sources"):
                    source = await self._host.persistence.sources.load_source(source_id)
                    if source:
                        await self._mark_failed(source, str(e))
            except Exception as e2:
                _sync_logger.warning(f"Не удалось обновить ошибку источника: {e2}")

            raise

    def entity_filter(self, source_id: UUID) -> set[str] | None:
        """Сущности, состояния которых синхронизация должна принимать.

        Это манифест **плюс** уже известные сервису сущности источника, а не
        манифест в одиночку:

        - в бою Home Assistant отдаёт 1502 сущности против 6 описанных, и остальные
          1496 попадали в `devices.json` молча — они не автоматизируются, но
          занимают место и время на каждую синхронизацию;
        - «только манифест» означал бы, что всё остальное помечается
          `removed_from_ha` (`_merge`), то есть фильтр отбирал бы устройства у
          живого дома.

        Пустой манифест означает отсутствие фильтра, а не пустой результат: иначе
        сборка без манифеста стала бы молчащей — устройств нет, синхронизация
        «успешна», и это неотличимо от поломки.

        Args:
            source_id: Идентификатор источника.

        Returns:
            Множество допустимых `ha_entity_id` либо `None`, если фильтр не
            применяется.
        """
        if self._host._manifest is None or not sync_filter_enabled():
            return None

        from core.events.event_router import collect_subscribed_entities

        allowed = set(collect_subscribed_entities(self._host._manifest))
        allowed |= self._known_entity_ids(source_id)
        return allowed

    def _known_entity_ids(self, source_id: UUID) -> set[str]:
        """Идентификаторы сущностей, уже известных сервису для источника.

        Известные сущности сохраняются при фильтрации: устройство, добавленное
        через интерфейс или найденное прошлой синхронизацией, не должно исчезать
        из базы только потому, что его нет в манифесте. Иначе фильтр сам
        становился бы причиной `removed_from_ha` — то есть снятия автоматики у
        живого устройства.

        Args:
            source_id: Идентификатор источника.

        Returns:
            Множество `ha_entity_id`, известных сервису для этого источника.
        """
        return {
            device.ha_entity_id
            for device in self._host._devices.values()
            if device.source_id == source_id and device.ha_entity_id
        }

    async def _fetch(self, source: HASource, source_id: UUID) -> list[Device]:
        """Прочитать состояния устройств источника Home Assistant.

        Args:
            source: Источник Home Assistant.
            source_id: Идентификатор источника (проставляется устройствам).

        Returns:
            Устройства, разобранные из состояний источника.

        Raises:
            RuntimeError: Если подключиться к источнику не удалось.
        """
        from adapters.home_assistant.rest_client import HARestClient

        async with HARestClient(source.url, source.token) as rest_client:
            if not await rest_client.connect_to_ha():
                raise RuntimeError(f"Не удалось подключиться к HA: {source.url}")

            ha_states = await rest_client.fetch_devices()

        allowed = self.entity_filter(source_id)
        if allowed is not None:
            before = len(ha_states)
            ha_states = [state for state in ha_states if state.get("entity_id") in allowed]
            _sync_logger.info(
                f"Фильтр синхронизации источника {source_id}: {len(ha_states)} из "
                f"{before} состояний (манифест + известные устройства)"
            )

        parsed_devices = self._host.parse_devices(ha_states)
        for device in parsed_devices:
            device.source_id = source_id
        _sync_logger.info(
            f"Преобразовано {len(parsed_devices)} устройств для источника {source_id} "
            f"(прочитано состояний: {len(ha_states)})"
        )
        return parsed_devices

    async def _merge(
        self, source_id: UUID, parsed_devices: list[Device]
    ) -> tuple[list[Device], list[Device]]:
        """Свести устройства из источника с уже известными.

        Существующие записи обновляются на месте (сохраняются идентификатор и
        выданные права), новые создаются, а пропавшие из Home Assistant
        помечаются статусом ``removed_from_ha`` — молча их не теряем.

        Args:
            source_id: Идентификатор источника.
            parsed_devices: Устройства, прочитанные из источника.

        Returns:
            Пара: актуальный список устройств источника и список исчезнувших.
        """
        known = await self._load_known(source_id)
        by_entity = {device.ha_entity_id: device for device in known}

        seen: set[str] = set()
        merged: list[Device] = []
        for fresh in parsed_devices:
            existing = by_entity.get(fresh.ha_entity_id)
            if existing is None:
                fresh.status = "available" if fresh.status != "unavailable" else "unavailable"
                await self._grant_access(fresh)
                merged.append(fresh)
                seen.add(fresh.ha_entity_id)
                continue

            existing.name = fresh.name
            existing.device_type = fresh.device_type
            existing.state = fresh.state
            existing.attributes = fresh.attributes
            existing.ha_area_id = fresh.ha_area_id
            existing.model = fresh.model
            existing.manufacturer = fresh.manufacturer
            existing.status = fresh.status
            existing.updated_at = datetime.utcnow()
            merged.append(existing)
            seen.add(existing.ha_entity_id)

        removed: list[Device] = []
        for device in known:
            if device.ha_entity_id in seen or device.status == "removed_from_ha":
                continue
            device.status = "removed_from_ha"
            device.updated_at = datetime.utcnow()
            removed.append(device)

        _sync_logger.info(
            f"Сведение синхронизации источника {source_id}: новых — "
            f"{sum(1 for d in merged if d not in known)}, исчезнувших — {len(removed)}"
        )
        return merged, removed

    async def _load_known(self, source_id: UUID) -> list[Device]:
        """Загрузить известные устройства источника из кэша и хранилища.

        Args:
            source_id: Идентификатор источника.

        Returns:
            Список устройств источника.
        """
        known: dict[UUID, Device] = {
            device_id: device
            for device_id, device in self._host._devices.items()
            if device.source_id == source_id
        }

        if self._host.persistence and hasattr(self._host.persistence, "devices"):
            try:
                stored = await self._host.persistence.devices.load_devices_by_source(source_id)
            except Exception as e:
                _sync_logger.warning(f"Не удалось загрузить устройства источника {source_id}: {e}")
                stored = []
            for device in stored:
                known.setdefault(device.id, device)

        return list(known.values())

    async def _grant_access(self, device: Device) -> None:
        """Выдать права на новое устройство владельцу инсталляции.

        Без этого устройство не попало бы в список: список отдаёт только
        устройства, доступные пользователю (spec 006, FR-015).

        Args:
            device: Новое устройство источника.
        """
        if self._host.persistence is None or not hasattr(self._host.persistence, "device_access"):
            return
        try:
            await self._host.grant_access(
                device_id=device.id,
                user_id=SYNC_ACCESS_USER,
                role="admin",
                granted_by=SYNC_ACCESS_USER,
            )
        except Exception as e:
            _sync_logger.warning(f"Не удалось выдать права на {device.ha_entity_id}: {e}")

    async def _deactivate_removed(self, removed: list[Device]) -> None:
        """Снять машины состояний устройств, исчезнувших из Home Assistant.

        Args:
            removed: Устройства, помеченные как removed_from_ha.
        """
        if not removed or self._host._engine is None:
            return

        unregistered = 0
        for device in removed:
            try:
                entities = self._host._engine.get_entities_by_device(device.ha_entity_id)
            except Exception as e:
                _sync_logger.warning(f"Не удалось найти автоматику {device.ha_entity_id}: {e}")
                continue
            for entity_id in entities:
                self._host._engine.unregister(entity_id)
                unregistered += 1

        if unregistered and self._host._event_router is not None:
            try:
                self._host._event_router.rebuild()
            except Exception as e:
                _sync_logger.warning(f"Не удалось перестроить маршрутизацию: {e}")

        _sync_logger.info(f"Снято машин состояний для исчезнувших устройств: {unregistered}")

    async def _mark_synced(self, source: HASource, device_count: int | None = None) -> None:
        """Зафиксировать успешную синхронизацию в метаданных источника.

        Обновляются не только время, но и состояние источника: `status` и
        `device_count`. Раньше здесь писалось только время, и оба поля оставались
        в прежнем значении — в бою это давало `status: disconnected` и
        `device_count: 0` при 1502 загруженных устройствах. Статус источника
        интерфейс берёт из этого поля, то есть показывал «Дом отключён» при
        работающем источнике.

        Args:
            source: Источник Home Assistant.
            device_count: Сколько устройств пришло из источника; при ``None``
                прежнее значение сохраняется (вызывающий может не знать числа).
        """
        source.last_sync = datetime.utcnow()
        source.last_error = None
        # Канонический статус, а не исторический `active`: API понимал оба
        # значения, но источник после синхронизации обязан иметь одно, иначе
        # следующая проверка снова столкнётся с двумя формами одного и того же.
        source.status = "connected"
        if device_count is not None:
            source.device_count = device_count
        if self._host.persistence and hasattr(self._host.persistence, "sources"):
            await self._host.persistence.sources.save_source(source)
            _sync_logger.info(
                f"Обновлено состояние источника {source.id}: status=connected, "
                f"устройств={source.device_count}"
            )

    async def _mark_failed(self, source: HASource, error: str) -> None:
        """Зафиксировать неудачную синхронизацию.

        Источник переводится в `disconnected`, а время последней **успешной**
        синхронизации не меняется: иначе оператор увидит свежую дату при данных
        трёхдневной давности, и расхождение не будет видно.

        Args:
            source: Источник Home Assistant.
            error: Текст ошибки для источника.
        """
        source.status = "disconnected"
        source.last_error = error
        if self._host.persistence and hasattr(self._host.persistence, "sources"):
            try:
                await self._host.persistence.sources.save_source(source)
            except Exception as save_error:  # noqa: BLE001 — отказ не должен ронять разбор
                _sync_logger.warning(f"Не удалось сохранить состояние источника: {save_error}")
        _sync_logger.warning(f"Синхронизация источника {source.id} не удалась: {error}")

    async def _persist_result(self, merged: list[Device], removed: list[Device]) -> None:
        """Зафиксировать результат синхронизации во всех хранилищах и событиях.

        Args:
            merged: Актуальные устройства источника.
            removed: Устройства, помеченные как removed_from_ha.
        """
        if self._host.persistence and hasattr(self._host.persistence, "devices"):
            await self._host.persistence.devices.save_devices(merged)
            _sync_logger.info(f"Сохранено {len(merged)} устройств в persistence")

        for device in merged:
            self._host._devices[device.id] = device
            self._host._index.add_device(device)
        for device in removed:
            self._host._devices[device.id] = device
            self._host._index.update_device(device)
        _sync_logger.info(
            f"Обновлены внутренние хранилища: записей — {len(merged)}, исчезнувших — {len(removed)}"
        )

        await self._deactivate_removed(removed)

        for device in merged:
            await self._host._publish_device_loaded_event(device)
        for device in removed:
            await self._host._publish_device_removed_event(device)
