"""Защита кондиционера: зимой и без разрешения владельца он не охлаждает.

Требование владельца 2026-10-15: «защита кондиционера зимой теперь на платформе».
Боевой случай: кондиционер гостиной стоял в режиме `cool` при `zima = on`, а
автоматизация «Защита кондиционера» в Home Assistant была выключена — защищать
было нечем.

Правило не зависит от автоматики: кондиционер может работать без участия
платформы (включён вручную или автоматизацией HA), поэтому служба смотрит
фактический режим прибора, а правила берёт те же, что и автоматы (`may_cool`).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from core.services.ac_protection import AirConditionerProtection


AC = "climate.esphome_web_0d22a4_ac_name"


@dataclass
class FakeAdapter:
    """Адаптер-двойник: режим прибора и правила дома.

    Attributes:
        modes: Сущность → режим прибора.
        rules: Правила дома (право владельца, сезон).
        fail: Бросать ли ошибку на чтении.
    """

    modes: dict[str, str] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    fail: bool = False

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать режимы приборов списком (так их читает защита).

        `get_entity_state` для климат-приборов отдаёт цель (`temperature`), а не
        режим: защите нужен именно режим, поэтому она берёт состояния списком.
        """
        if self.fail:
            raise RuntimeError("связи нет")
        return [{"entity_id": entity, "state": mode} for entity, mode in self.modes.items()]

    def event_context(self, entity_id: str | None = None) -> dict[str, Any]:
        """Отдать правила дома."""
        return dict(self.rules)


@dataclass
class FakeDispatcher:
    """Диспетчер-двойник: помнит отправленные команды."""

    sent: list[Any] = field(default_factory=list)

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду."""
        self.sent.append(intent)
        return True


def _protection(adapter: FakeAdapter, dispatcher: FakeDispatcher) -> AirConditionerProtection:
    """Собрать защиту с одним кондиционером.

    Args:
        adapter: Адаптер-двойник.
        dispatcher: Диспетчер-двойник.

    Returns:
        Служба защиты.
    """
    return AirConditionerProtection(adapter=adapter, dispatcher=dispatcher, entities=[AC])


@pytest.mark.asyncio
async def test_winter_stops_cooling() -> None:
    """Зима: кондиционер охлаждает — выключаем."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": True, "is_winter": True})
    dispatcher = FakeDispatcher()

    stopped = await _protection(adapter, dispatcher).check_once()

    assert stopped == [AC]
    assert len(dispatcher.sent) == 1
    intent = dispatcher.sent[0]
    assert intent.domain == "climate" and intent.service == "turn_off"
    assert intent.device_id == AC
    assert intent.bypass_lockout is True, "правило безопасности не отменяется блокировкой"


@pytest.mark.asyncio
async def test_owner_gate_off_stops_cooling() -> None:
    """Владелец не разрешил кондиционер — выключаем даже летом."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": False, "is_winter": False})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == [AC]
    assert dispatcher.sent, "команда не отправлена"


@pytest.mark.asyncio
async def test_auto_mode_counts_as_cooling() -> None:
    """`heat_cool` может охлаждать сам — зимой так же опасен, как `cool`."""
    adapter = FakeAdapter(modes={AC: "heat_cool"}, rules={"ac_allowed": True, "is_winter": True})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == [AC]


@pytest.mark.asyncio
async def test_allowed_cooling_is_left_alone() -> None:
    """Лето и разрешение владельца — кондиционер не трогаем."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": True, "is_winter": False})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_heating_is_not_touched() -> None:
    """Обогрев кондиционера защита не трогает: правило про охлаждение."""
    adapter = FakeAdapter(modes={AC: "heat"}, rules={"ac_allowed": True, "is_winter": True})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_off_state_is_not_touched() -> None:
    """Выключенный кондиционер нечего выключать."""
    adapter = FakeAdapter(modes={AC: "off"}, rules={"ac_allowed": False, "is_winter": True})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_unknown_state_is_not_guessed() -> None:
    """Прибор не ответил — защита не гадает и ничего не шлёт."""
    adapter = FakeAdapter(modes={}, rules={"ac_allowed": False, "is_winter": True})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_read_failure_does_not_raise() -> None:
    """Сбой чтения — не повод падать и не повод слать команду."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={}, fail=True)
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_season_unknown_does_not_forbid() -> None:
    """Сезон не прочитан — защита не гасит прибор наугад.

    Условие автоматики при неизвестном сезоне охлаждать не разрешает (цена ошибки
    — испорченная техника). Но защита **выключает работающий прибор**, поэтому
    действует только на известный запрет: иначе после старта, пока правила не
    прочитаны, законно работающий кондиционер гас бы зря.
    """
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": True, "is_winter": None})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_unknown_rules_do_not_stop_cooling_on_startup() -> None:
    """Правила ещё не прочитаны (старт платформы) — прибор не трогаем."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_explicit_gate_off_acts_even_without_season() -> None:
    """Запрет владельца известен точно — выключаем, даже если сезон не прочитан."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": False, "is_winter": None})
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == [AC]


@pytest.mark.asyncio
async def test_state_change_triggers_check() -> None:
    """Изменение состояния кондиционера проверяется сразу, а не в следующий проход."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": True, "is_winter": True})
    dispatcher = FakeDispatcher()
    protection = _protection(adapter, dispatcher)

    await protection._on_state_change(  # noqa: SLF001 — обработчик подписки
        "state_change", {"entity_id": AC}
    )

    assert dispatcher.sent, "изменение состояния не запустило проверку"


@pytest.mark.asyncio
async def test_other_entity_does_not_trigger_check() -> None:
    """Чужие состояния защиту не будят."""
    adapter = FakeAdapter(modes={AC: "cool"}, rules={"ac_allowed": True, "is_winter": True})
    dispatcher = FakeDispatcher()
    protection = _protection(adapter, dispatcher)

    await protection._on_state_change(  # noqa: SLF001 — обработчик подписки
        "state_change", {"entity_id": "light.svet_nad_stolom"}
    )

    assert dispatcher.sent == []


def test_no_entities_means_no_start() -> None:
    """В манифесте нет кондиционеров — защита не запускается."""
    protection = AirConditionerProtection(
        adapter=FakeAdapter(), dispatcher=FakeDispatcher(), entities=[]
    )

    assert protection.start() is False
