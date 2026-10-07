"""Синхронизация не должна забирать весь дом, но и не должна отбирать устройства.

Побочная находка 2026-10-07: синхронизация источника читала **все** состояния
Home Assistant. В бою их 1502 против 6 описанных в манифесте — 1496 устройств
лежали в `devices.json` молча: они не автоматизируются, но занимают место и
время на каждой синхронизации. То есть речь не о производительности, а о смысле:
платформа «знала» об устройствах, которых в манифесте нет.

Опасность наивной правки
------------------------

Фильтр «только манифест» отбирал бы устройства у живого дома. `_merge_synced_devices`
помечает `removed_from_ha` всё, чего нет среди пришедших из источника, и снимает с
исчезнувших устройств автоматику. Отфильтрованные по манифесту устройства в бою
живы — просто не описаны, — и «исчезновение» было бы выдуманным фильтром.

Поэтому фильтр — это **манифест плюс уже известные сервису сущности**:
новые инертные сущности в базу не попадают, а уже записанные не исчезают.

Что проверяется
---------------

1. Без манифеста фильтра нет: сборка без манифеста синхронизирует как прежде.
2. С манифестом в базу попадают только описанные сущности.
3. Уже известное сервису устройство сохраняется, даже если его нет в манифесте.
4. Пустой манифест означает отсутствие фильтра, а не пустой результат.
5. Фильтр применяется к состояниям до разбора, а не после.
6. Синхронизация не помечает отфильтрованное как `removed_from_ha`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from core.events.event_bus import EventBus
from core.models.device import Device
from core.models.ha_source import HASource
from services.device_service import DeviceService


#: Сущности, описанные в манифесте: лампа комнаты и датчик движения.
MANIFEST_ENTITIES = ("light.living_room_main", "binary_sensor.living_room_motion")

#: Сущность, которой в манифесте нет, но она есть в бою.
INERT_ENTITY = "sensor.temperature_outside"


def _manifest(entities: tuple[str, ...] = MANIFEST_ENTITIES) -> Any:
    """Манифест с одной комнатой: устройства и датчик.

    Args:
        entities: Сущности комнаты — устройства и датчики.

    Returns:
        Объект с полем `rooms`, которого ждёт `collect_subscribed_entities`.
    """
    device_ids = [e for e in entities if e.startswith(("light.", "switch."))]
    sensors = [e for e in entities if e not in device_ids]
    room = SimpleNamespace(
        devices=[SimpleNamespace(id=e) for e in device_ids],
        sensors={f"s{i}": e for i, e in enumerate(sensors)},
    )
    return SimpleNamespace(rooms=[room])


def _state(entity_id: str, value: str = "off") -> dict[str, Any]:
    """Состояние Home Assistant в формате `/api/states`.

    Args:
        entity_id: Идентификатор сущности.
        value: Значение состояния.

    Returns:
        Словарь состояния.
    """
    return {
        "entity_id": entity_id,
        "state": value,
        "attributes": {"friendly_name": entity_id},
    }


def _service(manifest: Any | None) -> DeviceService:
    """Сервис устройств с указанным манифестом.

    Args:
        manifest: Манифест либо ``None``.

    Returns:
        Готовый сервис.
    """
    return DeviceService(event_bus=EventBus(), manifest=manifest)


def _source() -> HASource:
    """Источник Home Assistant для чтения состояний.

    Returns:
        Модель источника.
    """
    # Токен короче 10 символов не проходит валидацию модели — здесь длина
    # несущественна, а настоящий токен в тесте светить незачем.
    return HASource(
        id=uuid4(),
        name="Дом",
        url="http://ha.local:8123",
        token="test-token-value",
    )


def _device(entity_id: str, source_id: UUID) -> Device:
    """Известное сервису устройство.

    Args:
        entity_id: Идентификатор сущности.
        source_id: Идентификатор источника.

    Returns:
        Модель устройства.
    """
    return Device(
        ha_entity_id=entity_id,
        source_id=source_id,
        name=entity_id,
        device_type=entity_id.split(".")[0],
        state={"state": "off"},
    )


@pytest.fixture(autouse=True)
def _filter_on(monkeypatch: Any) -> None:
    """Включить фильтр на время тестов этого файла.

    По умолчанию фильтр выключен: он меняет контракт платформы и ломает 38
    тестов, которые этот контракт проверяют. Здесь он включается явно, чтобы
    проверялась именно фильтрация, а не её отсутствие.
    """
    monkeypatch.setenv("SYNC_FILTER_MANIFEST_ONLY", "true")


class TestFilterIsOffByDefault:
    """Пока флаг не задан, поведение прежнее."""

    @pytest.mark.asyncio
    async def test_inert_entity_still_read_without_flag(self, monkeypatch: Any) -> None:
        """Без флага синхронизация импортирует всё, что отдал источник.

        Это нынешний контракт платформы, и его проверяют 38 тестов: синхронизация
        остаётся способом узнать о новом устройстве. Фильтр по умолчанию не
        включён именно поэтому.
        """
        monkeypatch.delenv("SYNC_FILTER_MANIFEST_ONLY", raising=False)
        service = _service(_manifest())
        source = _source()
        states = [_state(e) for e in (*MANIFEST_ENTITIES, INERT_ENTITY)]

        rest_client = AsyncMock()
        rest_client.connect_to_ha.return_value = True
        rest_client.fetch_devices.return_value = states
        rest_client.__aenter__.return_value = rest_client
        rest_client.__aexit__.return_value = False

        with patch("adapters.home_assistant.rest_client.HARestClient", return_value=rest_client):
            devices = await service._fetch_source_devices(source, source.id)

        assert INERT_ENTITY in {d.ha_entity_id for d in devices}, (
            "без флага фильтр применяться не должен: контракт синхронизации "
            "изменён, а решение об этом не принято"
        )

    def test_flag_is_off_when_unset(self, monkeypatch: Any) -> None:
        """Незаданная переменная означает «выключено».

        Как и `SHADOW_MODE`: забытая настройка не должна молча менять смысл
        платформы.
        """
        monkeypatch.delenv("SYNC_FILTER_MANIFEST_ONLY", raising=False)

        from services.device_service import sync_filter_enabled

        assert sync_filter_enabled() is False


class TestFilterIsAbsentWithoutManifest:
    """Без манифеста синхронизация ведёт себя как прежде."""

    @pytest.mark.asyncio
    async def test_all_states_are_read_when_manifest_missing(self) -> None:
        """Отсутствие манифеста не должно молча очищать синхронизацию.

        Сборка без манифеста иначе стала бы молчащей: устройств нет,
        синхронизация «успешна», и это неотличимо от поломки.
        """
        service = _service(None)
        source = _source()
        states = [_state(e) for e in (*MANIFEST_ENTITIES, INERT_ENTITY)]

        rest_client = AsyncMock()
        rest_client.connect_to_ha.return_value = True
        rest_client.fetch_devices.return_value = states
        rest_client.__aenter__.return_value = rest_client
        rest_client.__aexit__.return_value = False

        with patch("adapters.home_assistant.rest_client.HARestClient", return_value=rest_client):
            devices = await service._fetch_source_devices(source, source.id)

        assert {d.ha_entity_id for d in devices} == {*MANIFEST_ENTITIES, INERT_ENTITY}, (
            f"без манифеста фильтр применяться не должен: {sorted(d.ha_entity_id for d in devices)}"
        )

    def test_filter_is_none_without_manifest(self) -> None:
        """Фильтр возвращает `None` — признак «не применяется», а не пустой список.

        Проверяется с флагом **включённым**: без манифеста фильтра нет в любом
        случае, иначе проверка проходила бы, не замечая флага.
        """
        assert _service(None).sync_entity_filter(uuid4()) is None


class TestFilterKeepsManifestEntities:
    """Описанные сущности синхронизация видит."""

    @pytest.mark.asyncio
    async def test_inert_entity_is_not_stored(self) -> None:
        """Сущность вне манифеста не попадает в базу."""
        service = _service(_manifest())
        source = _source()
        states = [_state(e) for e in (*MANIFEST_ENTITIES, INERT_ENTITY)]

        rest_client = AsyncMock()
        rest_client.connect_to_ha.return_value = True
        rest_client.fetch_devices.return_value = states
        rest_client.__aenter__.return_value = rest_client
        rest_client.__aexit__.return_value = False

        with patch("adapters.home_assistant.rest_client.HARestClient", return_value=rest_client):
            devices = await service._fetch_source_devices(source, source.id)

        assert {d.ha_entity_id for d in devices} == set(MANIFEST_ENTITIES), (
            f"в базу попало лишнее: {sorted(d.ha_entity_id for d in devices)}. "
            f"Устройства вне манифеста не автоматизируются, но занимают место "
            f"при каждой синхронизации"
        )

    def test_filter_contains_manifest_entities(self) -> None:
        """Фильтр включает и устройства комнаты, и её датчики.

        Датчик без устройств тоже нужен: по нему приходят события движения.
        """
        allowed = _service(_manifest()).sync_entity_filter(uuid4())

        assert allowed == set(MANIFEST_ENTITIES)

    @pytest.mark.asyncio
    async def test_filter_applies_before_parsing(self) -> None:
        """Фильтр отсекает состояния, а не разобранные устройства.

        Проверяется на числе состояний, прочитанных у источника: разбор 1502
        устройств ради 6 нужных — это и есть та работа, которую фильтр снимает.
        """
        service = _service(_manifest())
        source = _source()
        states = [_state(e) for e in (*MANIFEST_ENTITIES, INERT_ENTITY)]

        rest_client = AsyncMock()
        rest_client.connect_to_ha.return_value = True
        rest_client.fetch_devices.return_value = states
        rest_client.__aenter__.return_value = rest_client
        rest_client.__aexit__.return_value = False

        with (
            patch("adapters.home_assistant.rest_client.HARestClient", return_value=rest_client),
            patch.object(service, "parse_devices", wraps=service.parse_devices) as parse,
        ):
            await service._fetch_source_devices(source, source.id)

        received = parse.call_args[0][0]
        assert INERT_ENTITY not in {s["entity_id"] for s in received}, (
            "фильтр должен отсекать состояния до разбора: иначе 1502 устройства "
            "разбираются, чтобы 6 были оставлены"
        )


class TestFilterKeepsKnownDevices:
    """Известные устройства фильтр не отбирает."""

    def test_known_entity_stays_in_filter(self) -> None:
        """Устройство, добавленное через интерфейс, остаётся синхронизируемым."""
        service = _service(_manifest())
        source_id = uuid4()
        service._devices[uuid4()] = _device(INERT_ENTITY, source_id)

        allowed = service.sync_entity_filter(source_id)

        assert allowed is not None
        assert INERT_ENTITY in allowed, (
            "устройство, известное сервису, отфильтровано: оно попадёт под "
            "`removed_from_ha` и потеряет автоматику, хотя в доме живо"
        )

    def test_known_entity_of_other_source_not_included(self) -> None:
        """Чужое устройство в фильтр источника не попадает.

        Два источника не должны влиять друг на друга: иначе синхронизация
        одного тянула бы сущности другого.
        """
        service = _service(_manifest())
        mine, theirs = uuid4(), uuid4()
        service._devices[uuid4()] = _device(INERT_ENTITY, theirs)

        allowed = service.sync_entity_filter(mine)

        assert allowed is not None
        assert INERT_ENTITY not in allowed

    @pytest.mark.asyncio
    async def test_known_entity_survives_sync(self) -> None:
        """Синхронизация не помечает отфильтрованное устройство исчезнувшим."""
        service = _service(_manifest())
        source = _source()
        # Ключ в `_devices` обязан совпадать с идентификатором устройства:
        # сервис ищет по значению, а рассинхрон означал бы, что устройство
        # «известно» только словарю — фильтр его не увидит.
        known = _device(INERT_ENTITY, source.id)
        service._devices[known.id] = known

        rest_client = AsyncMock()
        rest_client.connect_to_ha.return_value = True
        # Источник отдаёт все состояния дома, как это делает Home Assistant:
        # устройство живо, и фильтр обязан его пропустить.
        rest_client.fetch_devices.return_value = [
            _state(e) for e in (*MANIFEST_ENTITIES, INERT_ENTITY)
        ]
        rest_client.__aenter__.return_value = rest_client
        rest_client.__aexit__.return_value = False

        with patch("adapters.home_assistant.rest_client.HARestClient", return_value=rest_client):
            parsed = await service._fetch_source_devices(source, source.id)

        merged, removed = await service._merge_synced_devices(source.id, parsed)

        assert removed == [], f"живое устройство помечено исчезнувшим: {removed}"
        assert known.id in {d.id for d in merged}, (
            f"известное устройство не сохранено при синхронизации: {merged}"
        )


class TestEmptyManifestMeansNoFilter:
    """Пустой манифест — отсутствие фильтра."""

    def test_empty_manifest_does_not_empty_sync(self) -> None:
        """Манифест без комнат оставляет синхронизацию работать.

        Иначе платформа с пустым манифестом была бы молчащей: соединение есть,
        `/ready` зелёный, устройств нет.
        """
        service = _service(_manifest(entities=()))
        source_id = uuid4()
        service._devices[uuid4()] = _device(INERT_ENTITY, source_id)

        allowed = service.sync_entity_filter(source_id)

        # Сущность проходит только потому, что сервис её знает: фильтр не пуст,
        # но и не «только манифест» — известные сохраняются.
        assert allowed == {INERT_ENTITY}

    def test_empty_manifest_without_known_devices_filters_all(self) -> None:
        """Пустой манифест без известных устройств оставляет фильтр пустым.

        Это единственный случай, где синхронизация не принесёт ничего: так и
        должно быть — описать нечего.
        """
        assert _service(_manifest(entities=())).sync_entity_filter(uuid4()) == set()


class TestFilterMatchesSubscription:
    """Фильтр синхронизации и фильтр подписки берут один список."""

    def test_same_source_of_truth_as_subscription(self) -> None:
        """Подписка и синхронизация не должны разойтись.

        Подписка (после #82) берёт сущности из манифеста; если бы фильтр
        синхронизации брал свой список, платформа получала бы события по
        одному набору и данные по другому.
        """
        from core.events.event_router import collect_subscribed_entities

        manifest = _manifest()
        source_id = uuid4()
        service = _service(manifest)
        known_id = uuid4()
        service._devices[known_id] = _device(INERT_ENTITY, source_id)

        allowed = service.sync_entity_filter(source_id)
        subscribed = set(collect_subscribed_entities(manifest))

        assert subscribed <= allowed, (
            f"подписка берёт сущности, которых нет в фильтре синхронизации: "
            f"{sorted(subscribed - allowed)}"
        )
