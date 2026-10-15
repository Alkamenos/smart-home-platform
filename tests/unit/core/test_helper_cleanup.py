"""Чистка вспомогательных элементов: признак использования по фактам (B77).

Главное, что проверяется: «не используется» платформа говорит только тогда,
когда **все** источники свидетельств ответили. Иначе вердикт — «не знаю»:
предложить удалить живое хуже, чем промолчать.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest

from core.services.helper_cleanup import (
    PROBABLY_UNUSED,
    UNKNOWN,
    USED,
    HelperCleanupService,
)


NOW = 1_800_000_000.0


def _state(
    entity_id: str, state: str = "off", *, name: str | None = None, changed: float | None = None
) -> dict[str, Any]:
    """Состояние сущности, как его отдаёт Home Assistant.

    Args:
        entity_id: Сущность.
        state: Состояние.
        name: Понятное имя.
        changed: Когда менялось (epoch).

    Returns:
        Словарь состояния.
    """
    from datetime import datetime

    attributes: dict[str, Any] = {"friendly_name": name or entity_id}
    payload: dict[str, Any] = {"entity_id": entity_id, "state": state, "attributes": attributes}
    if changed is not None:
        payload["last_changed"] = datetime.fromtimestamp(changed, UTC).isoformat()
    return payload


class FakeAdapter:
    """Адаптер: состояния дома и правила автоматизаций."""

    def __init__(
        self,
        states: list[dict[str, Any]] | None = None,
        automations: dict[str, Any] | None = None,
        states_ok: bool = True,
        automations_ok: bool = True,
    ) -> None:
        """Собрать поддельный адаптер.

        Args:
            states: Состояния сущностей.
            automations: Правила автоматизаций по идентификатору.
            states_ok: Отвечает ли дом на чтение состояний.
            automations_ok: Удалось ли прочитать автоматизации.
        """
        self.states = states or []
        self.automations = automations or {}
        self.states_ok = states_ok
        self.automations_ok = automations_ok
        self.state_reads = 0

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Состояния всех сущностей.

        Returns:
            Список состояний (пусто, если дом не ответил).
        """
        self.state_reads += 1
        return self.states if self.states_ok else []

    async def get_automation_configs(self) -> dict[str, Any]:
        """Правила автоматизаций.

        Returns:
            Правила по идентификатору (пусто, если прочитать не удалось).
        """
        return self.automations if self.automations_ok else {}


class FakeManifest:
    """Манифест: только та часть, которая нужна чистке."""

    def __init__(self, entities: list[str]) -> None:
        """Собрать поддельный манифест.

        Args:
            entities: Сущности, упомянутые в манифесте.
        """
        self._entities = entities

    def model_dump(self) -> dict[str, Any]:
        """Представление манифеста словарём.

        Returns:
            Словарь с упомянутыми сущностями.
        """
        return {
            "automation_rules": {"lighting": {"sleep_modifier": self._entities}},
            "rooms": [{"id": "gostinnaia", "name": "Гостиная"}],
        }


class FakeEventStore:
    """Журнал: какие сущности встречались."""

    def __init__(self, seen: list[str]) -> None:
        """Собрать поддельный журнал.

        Args:
            seen: Сущности, у которых были события.
        """
        self.seen = seen

    def get_events_for_entities(self, entity_ids: Any, **_: Any) -> list[dict[str, Any]]:
        """События по сущностям.

        Args:
            entity_ids: Какие сущности спрашиваем.
            **_: Прочие доводы (срок, предел) — здесь не нужны.

        Returns:
            События по тем сущностям, что есть в журнале.
        """
        wanted = set(entity_ids)
        return [{"entity_id": entity} for entity in self.seen if entity in wanted]


def _service(
    states: list[dict[str, Any]],
    *,
    manifest: Any = None,
    automations: dict[str, Any] | None = None,
    journal: Any = None,
    states_ok: bool = True,
    automations_ok: bool = True,
) -> HelperCleanupService:
    """Собрать службу чистки для проверки.

    Args:
        states: Состояния дома.
        manifest: Манифест.
        automations: Правила автоматизаций.
        journal: Журнал платформы.
        states_ok: Отвечает ли дом.
        automations_ok: Читаются ли автоматизации.

    Returns:
        Служба чистки.
    """
    return HelperCleanupService(
        adapter=FakeAdapter(
            states=states,
            automations=automations,
            states_ok=states_ok,
            automations_ok=automations_ok,
        ),
        manifest=manifest,
        event_store=journal,
        clock=lambda: NOW,
    )


def _verdict(report: dict[str, Any], entity_id: str) -> dict[str, Any]:
    """Найти вердикт по сущности.

    Args:
        report: Снимок чистки.
        entity_id: Сущность.

    Returns:
        Описание элемента с вердиктом.

    Raises:
        AssertionError: Если сущности нет в снимке.
    """
    for helper in report["helpers"]:
        if helper["entity_id"] == entity_id:
            return helper
    msg = f"в снимке нет {entity_id}"
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_manifest_reference_marks_used() -> None:
    """Элемент из манифеста дома — используется."""
    service = _service(
        [_state("input_boolean.sleep_mode")],
        manifest=FakeManifest(["input_boolean.sleep_mode"]),
    )

    report = await service.sweep()

    helper = _verdict(report, "input_boolean.sleep_mode")
    assert helper["verdict"] == USED
    assert helper["reasons"][0]["source"] == "manifest"


@pytest.mark.asyncio
async def test_automation_reference_marks_used() -> None:
    """Элемент, нужный чужой автоматизации Home Assistant, — используется."""
    service = _service(
        [_state("input_boolean.guests")],
        manifest=FakeManifest([]),
        automations={
            "1": {
                "alias": "Свет для гостей",
                "trigger": [{"platform": "state", "entity_id": "input_boolean.guests"}],
                "action": [{"service": "light.turn_on", "target": {"entity_id": "light.hall"}}],
            }
        },
    )

    report = await service.sweep()

    helper = _verdict(report, "input_boolean.guests")
    assert helper["verdict"] == USED, "элемент выбросили бы, хотя им пользуется автоматизация"
    assert [reason["source"] for reason in helper["reasons"]] == ["automation"]


@pytest.mark.asyncio
async def test_journal_reference_marks_used() -> None:
    """Элемент, встречавшийся в журнале, — используется."""
    service = _service(
        [_state("input_number.temperatura_zhelannaia")],
        manifest=FakeManifest([]),
        journal=FakeEventStore(["input_number.temperatura_zhelannaia"]),
    )

    report = await service.sweep()

    helper = _verdict(report, "input_number.temperatura_zhelannaia")
    assert helper["verdict"] == USED
    assert [reason["source"] for reason in helper["reasons"]] == ["journal"]


@pytest.mark.asyncio
async def test_no_evidence_marks_candidate() -> None:
    """Без свидетельств и при живых источниках — кандидат на удаление."""
    service = _service(
        [_state("input_boolean.staryi_flag")],
        manifest=FakeManifest([]),
        automations={"1": {"alias": "Что-то", "action": []}},
    )

    report = await service.sweep()

    helper = _verdict(report, "input_boolean.staryi_flag")
    assert helper["verdict"] == PROBABLY_UNUSED
    assert helper["reasons"] == []


@pytest.mark.asyncio
async def test_unreadable_automations_give_unknown() -> None:
    """Автоматизации не прочитались — вердикт «не знаю», а не «мусор»."""
    service = _service(
        [_state("input_boolean.staryi_flag")],
        manifest=FakeManifest([]),
        automations_ok=False,
    )

    report = await service.sweep()

    assert _verdict(report, "input_boolean.staryi_flag")["verdict"] == UNKNOWN
    assert report["sources"]["automations"] is False


@pytest.mark.asyncio
async def test_silent_house_gives_unknown() -> None:
    """Дом не ответил — чистка молчит, а не предлагает удалять."""
    service = _service([], manifest=FakeManifest([]), states_ok=False)

    report = await service.sweep()

    assert report["helpers"] == []
    assert report["sources"]["states"] is False


@pytest.mark.asyncio
async def test_devices_are_not_helpers() -> None:
    """Приборы дома чистка не трогает — только вспомогательные элементы."""
    service = _service(
        [
            _state("light.gostinaia_liustra", "on"),
            _state("sensor.datchik_temperatury_sad_temperature", "22.4"),
            _state("input_boolean.staryi_flag"),
        ],
        manifest=FakeManifest([]),
        automations={"1": {"alias": "Что-то", "action": []}},
    )

    report = await service.sweep()

    assert [helper["entity_id"] for helper in report["helpers"]] == ["input_boolean.staryi_flag"]


@pytest.mark.asyncio
async def test_candidates_come_first() -> None:
    """Кандидаты на удаление — в начале списка."""
    service = _service(
        [_state("input_boolean.zhivoi"), _state("input_boolean.mertvyi")],
        manifest=FakeManifest(["input_boolean.zhivoi"]),
        automations={"1": {"alias": "Что-то", "action": []}},
    )

    report = await service.sweep()

    assert [helper["entity_id"] for helper in report["helpers"]] == [
        "input_boolean.mertvyi",
        "input_boolean.zhivoi",
    ]
    assert report["counts"] == {USED: 1, PROBABLY_UNUSED: 1, UNKNOWN: 0}


@pytest.mark.asyncio
async def test_snapshot_is_cached_until_forced() -> None:
    """Повторный запрос страницы не обходит дом заново."""
    service = _service(
        [_state("input_boolean.staryi_flag")],
        manifest=FakeManifest([]),
        automations={"1": {"alias": "Что-то", "action": []}},
    )

    await service.sweep()
    await service.sweep()
    reads_after_cache = service._adapter.state_reads  # noqa: SLF001 - проверяем кэш
    await service.sweep(force=True)

    assert reads_after_cache == 1, "снимок собирался второй раз без нужды"
    assert service._adapter.state_reads == 2, "принудительный сбор не обошёл дом"  # noqa: SLF001
