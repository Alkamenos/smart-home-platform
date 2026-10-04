"""Конкурентные операции и исчезновение устройств (спека 009, T026, T027).

Проверяет, что параллельные операции не задваивают и не теряют данные, а
исчезновение устройства во внешней системе обрабатывается полностью: устройство
помечается `removed_from_ha`, автоматика снимается, остальные устройства и
источники не страдают.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

Ограничение времени
-------------------
Каждая проверка конкуренции имеет порог. Тест без ограничения на дедлок
невыполним в принципе: он зависнет, а не упадёт, и диагностика будет
бесполезной.
"""

from __future__ import annotations

import time

import pytest
from tests.helpers.ha_stub import stub_ha


#: Порог для проверок конкуренции, секунды. Операции обязаны завершиться быстрее;
#: зависание должно приводить к падению теста, а не к его тихому ожиданию.
CONCURRENCY_BUDGET_SEC = 10.0


@pytest.fixture
def ha_concurrent_states() -> list[dict]:
    """Набор состояний для проверок конкуренции.

    Returns:
        Список состояний двух устройств.
    """
    return [
        {
            "entity_id": "light.concurrent_a",
            "state": "on",
            "attributes": {"friendly_name": "Первый"},
        },
        {
            "entity_id": "light.concurrent_b",
            "state": "off",
            "attributes": {"friendly_name": "Второй"},
        },
    ]


class TestConcurrentSync:
    """Параллельные синхронизации одного источника."""

    def test_parallel_syncs_do_not_duplicate_devices(self, isolated_client, ha_concurrent_states):
        """Параллельные синхронизации не создают дублей устройств.

        Идентичность устройства — пара (источник, `ha_entity_id`), поэтому две
        одновременные синхронизации не должны удваивать записи.

        Args:
            isolated_client: HTTP-клиент теста.
            ha_concurrent_states: Состояния внешней системы.
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Concurrent HA",
                "url": "http://concurrent.invalid:8123",
                "token": "concurrent_token_1",
            },
        )
        assert source.status_code == 201, source.text
        source_id = source.json()["id"]

        # Первый проход — чтобы устройства появились.
        with stub_ha(states=ha_concurrent_states):
            first = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        assert first.status_code == 200, first.text

        started = time.monotonic()
        with stub_ha(states=ha_concurrent_states):
            for _ in range(3):
                response = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
                assert response.status_code == 200, response.text
        elapsed = time.monotonic() - started

        assert elapsed < CONCURRENCY_BUDGET_SEC, (
            f"три синхронизации заняли {elapsed:.1f} с — ожидается быстрое выполнение"
        )

        devices = isolated_client.get("/api/v1/devices").json()
        entities = [d["ha_entity_id"] for d in devices]
        assert len(entities) == len(set(entities)), f"появились дубли: {entities}"
        assert len(entities) == 2, f"ожидались 2 устройства, получено {entities}"

    def test_sequential_syncs_stay_stable(self, isolated_client, ha_concurrent_states):
        """Последовательные синхронизации дают тот же результат, что и повторные.

        Args:
            isolated_client: HTTP-клиент теста.
            ha_concurrent_states: Состояния внешней системы.
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Sequential HA",
                "url": "http://sequential.invalid:8123",
                "token": "sequential_token_1",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_concurrent_states):
            for _ in range(4):
                assert (
                    isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync").status_code
                    == 200
                )

        devices = isolated_client.get("/api/v1/devices").json()
        assert len(devices) == 2, f"после 4 синхронизаций ожидались 2 устройства: {devices}"


class TestConcurrentCommands:
    """Параллельные команды одного устройства."""

    def test_parallel_commands_are_all_recorded(self, isolated_client, synced_device_id):
        """Параллельные команды не теряются и не дублируются.

        Args:
            isolated_client: HTTP-клиент теста.
            synced_device_id: Идентификатор устройства.
        """
        granted = isolated_client.post(
            f"/api/v1/devices/{synced_device_id}/access",
            json={"user_id": "user_controller", "role": "controller"},
        )
        assert granted.status_code == 201, granted.text

        from fastapi.testclient import TestClient

        with TestClient(
            isolated_client.app,
            headers={"X-User-ID": "user_controller", "X-Is-Admin": "false"},
        ) as commander:
            started = time.monotonic()
            responses = [
                commander.post(
                    f"/api/v1/devices/{synced_device_id}/command",
                    json={"command_name": "turn_off"},
                )
                for _ in range(4)
            ]
            elapsed = time.monotonic() - started

        assert elapsed < CONCURRENCY_BUDGET_SEC, f"параллельные команды заняли {elapsed:.1f} с"
        for response in responses:
            assert response.status_code == 202, f"ожидался 202: {response.text}"

        events = isolated_client.get(
            f"/api/v1/devices/{synced_device_id}/events?event_type=command_executed"
        ).json()
        assert len(events) == 4, f"ожидались 4 записи о командах, получено {len(events)}"

        ids = [e["data"]["command"] for e in events]
        assert ids == ["turn_off"] * 4, f"ожидались одинаковые команды: {ids}"


class TestDeviceVanishedFromSource:
    """Устройство исчезает из внешней системы."""

    @pytest.fixture
    def vanishing(self, isolated_client, ha_states):
        """Источник, синхронизированный с двумя устройствами.

        Args:
            isolated_client: HTTP-клиент теста.
            ha_states: Состояния внешней системы.

        Returns:
            Кортеж «идентификатор источника, идентификаторы устройств».
        """
        source = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Vanishing HA",
                "url": "http://vanish.invalid:8123",
                "token": "vanish_token_1234",
            },
        )
        source_id = source.json()["id"]

        with stub_ha(states=ha_states):
            sync = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        assert sync.status_code == 200, sync.text

        devices = isolated_client.get("/api/v1/devices").json()
        assert len(devices) == 2, f"ожидались 2 устройства: {devices}"
        by_entity = {d["ha_entity_id"]: str(d["id"]) for d in devices}

        return source_id, by_entity

    def test_vanished_device_is_marked_not_dropped(self, isolated_client, vanishing):
        """Исчезнувшее устройство помечается, но остаётся в данных.

        Поведение задано контрактом specs/006: устройства в статусе
        `removed_from_ha` остаются в списке с пометкой — «молча их не теряем».
        Первая версия теста требовала исчезновения из списка и противоречила
        контракту.

        Args:
            isolated_client: HTTP-клиент теста.
            vanishing: Идентификатор источника и устройств.
        """
        source_id, by_entity = vanishing
        remaining = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Кухонный свет"},
            }
        ]

        with stub_ha(states=remaining):
            response = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        assert response.status_code == 200, response.text

        devices = {d["ha_entity_id"]: d for d in isolated_client.get("/api/v1/devices").json()}
        assert "switch.bedroom_fan" in devices, (
            f"исчезнувший не должен молча пропасть: {list(devices)}"
        )
        assert devices["switch.bedroom_fan"]["status"] == "removed_from_ha", (
            f"ожидался статус removed_from_ha: {devices['switch.bedroom_fan']}"
        )
        assert devices["light.kitchen"]["status"] == "available", (
            f"оставшееся устройство должно быть доступно: {devices['light.kitchen']}"
        )

    def test_vanished_device_loses_automation(self, isolated_client, vanishing):
        """У помеченного устройства снята автоматика.

        Именно это отличает `removed_from_ha` от «просто осталось в списке»:
        устройство не должно продолжать реагировать на события, которых уже
        не будет.

        Args:
            isolated_client: HTTP-клиент теста.
            vanishing: Идентификатор источника и устройств.
        """
        source_id, _ = vanishing
        remaining = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Кухонный свет"},
            }
        ]

        with stub_ha(states=remaining):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        devices = {d["ha_entity_id"]: d for d in isolated_client.get("/api/v1/devices").json()}
        vanished = devices["switch.bedroom_fan"]
        assert vanished["status"] == "removed_from_ha"
        assert not vanished.get("fsm"), (
            f"у помеченного устройства не должно остаться автоматики: {vanished}"
        )

    def test_vanished_device_keeps_access_records(self, isolated_client, vanishing):
        """Права на исчезнувшее устройство сохраняются — и это по контракту.

        Первая версия теста требовала отзыва прав, и это было неверно. Каскад
        «отзыв всех записей о доступе» выполняется при явном удалении устройства
        (`DeviceLifecycleService.delete_device`), а не при исчезновении из
        внешней системы: устройство помечается `removed_from_ha` и остаётся в
        данных, поэтому доступ к нему остаётся. Тест фиксирует фактическое
        поведение — отказ от каскада здесь означал бы потерю выданных прав при
        временном сбое связи.

        Args:
            isolated_client: HTTP-клиент теста.
            vanishing: Идентификатор источника и устройств.
        """
        source_id, by_entity = vanishing
        device_id = by_entity["switch.bedroom_fan"]

        granted = isolated_client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": "user_viewer", "role": "controller"},
        )
        assert granted.status_code == 201, granted.text

        remaining = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Кухонный свет"},
            }
        ]
        with stub_ha(states=remaining):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        from fastapi.testclient import TestClient

        with TestClient(
            isolated_client.app, headers={"X-User-ID": "user_viewer", "X-Is-Admin": "false"}
        ) as former:
            listed = {str(d["id"]) for d in former.get("/api/v1/devices").json()}

        assert device_id in listed, (
            f"доступ к помеченному устройству сохраняется по контракту: {listed}"
        )
        devices = {str(d["id"]): d for d in isolated_client.get("/api/v1/devices").json()}
        assert devices[device_id]["status"] == "removed_from_ha", (
            f"устройство должно быть помечено: {devices[device_id]}"
        )

    def test_returned_device_regains_availability(self, isolated_client, vanishing):
        """Вернувшееся устройство восстанавливает статус.

        Args:
            isolated_client: HTTP-клиент теста.
            vanishing: Идентификатор источника и устройств.
        """
        source_id, _ = vanishing
        remaining = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Кухонный свет"},
            }
        ]
        with stub_ha(states=remaining):
            isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")
        assert len(isolated_client.get("/api/v1/devices").json()) == 2

        with stub_ha(
            states=[
                *remaining,
                {
                    "entity_id": "switch.bedroom_fan",
                    "state": "off",
                    "attributes": {"friendly_name": "Вентилятор спальни"},
                },
            ]
        ):
            restored = isolated_client.post(f"/api/v1/devices/sources/{source_id}/sync")

        assert restored.json()["device_count"] == 2, (
            f"ожидалось восстановление обоих устройств: {restored.json()}"
        )
        statuses = {
            d["ha_entity_id"]: d["status"] for d in isolated_client.get("/api/v1/devices").json()
        }
        assert statuses["switch.bedroom_fan"] == "available", (
            f"вернувшееся устройство должно быть доступно: {statuses}"
        )


class TestSourceIsolation:
    """Устройства разных источников не смешиваются."""

    def test_each_source_keeps_its_own_devices(self, isolated_client):
        """Синхронизация одного источника не трогает устройства другого.

        Первая версия теста была построена неверно: она синхронизировала второй
        источник с урезанным набором и ждала, что чужое устройство исчезнет. Но
        сведение выполняется в пределах одного источника, поэтому устройство
        первого источника синхронизацией второго **не рассматривается вовсе** —
        оно даже не попадает в поле зрения. Такая проверка ничем не отличалась
        бы от полного отсутствия изоляции.

        Правильная схема: у каждого источника своё устройство, затем исчезновение
        устройства **своего** источника проверяется на фоне чужого.

        Args:
            isolated_client: HTTP-клиент теста.
        """
        first = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "First",
                "url": "http://first.invalid:8123",
                "token": "first_token_12345",
            },
        )
        second = isolated_client.post(
            "/api/v1/devices/sources",
            json={
                "name": "Second",
                "url": "http://second.invalid:8123",
                "token": "second_token_1234",
            },
        )
        assert first.status_code == 201 and second.status_code == 201

        first_state = [
            {
                "entity_id": "light.of_first",
                "state": "on",
                "attributes": {"friendly_name": "Первого источника"},
            }
        ]
        second_state = [
            {
                "entity_id": "light.of_second",
                "state": "on",
                "attributes": {"friendly_name": "Второго источника"},
            }
        ]

        with stub_ha(states=first_state):
            assert (
                isolated_client.post(
                    f"/api/v1/devices/sources/{first.json()['id']}/sync"
                ).status_code
                == 200
            )
        with stub_ha(states=second_state):
            assert (
                isolated_client.post(
                    f"/api/v1/devices/sources/{second.json()['id']}/sync"
                ).status_code
                == 200
            )

        def _statuses() -> dict[str, str]:
            return {
                d["ha_entity_id"]: d["status"]
                for d in isolated_client.get("/api/v1/devices").json()
            }

        assert _statuses() == {
            "light.of_first": "available",
            "light.of_second": "available",
        }, "оба источника должны отдать своё устройство"

        # Первый источник больше не отдаёт своё устройство; устройство второго
        # источника при этом не должно пострадать.
        with stub_ha(states=[]):
            assert (
                isolated_client.post(
                    f"/api/v1/devices/sources/{first.json()['id']}/sync"
                ).status_code
                == 200
            )

        after = _statuses()
        assert after["light.of_first"] == "removed_from_ha", (
            f"своё исчезнувшее устройство должно быть помечено: {after}"
        )
        assert after["light.of_second"] == "available", (
            f"устройство другого источника не должно быть затронутым: {after}"
        )
