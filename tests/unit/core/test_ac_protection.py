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


def _protection(
    adapter: FakeAdapter, dispatcher: FakeDispatcher, min_temp: float = 5.0
) -> AirConditionerProtection:
    """Собрать защиту с одним кондиционером.

    Args:
        adapter: Адаптер-двойник.
        dispatcher: Диспетчер-двойник.
        min_temp: Порог уличной температуры.

    Returns:
        Служба защиты.
    """
    return AirConditionerProtection(
        adapter=adapter,
        dispatcher=dispatcher,
        entities=[AC],
        min_outside_temp=min_temp,
    )


@pytest.mark.asyncio
async def test_freezing_outside_stops_cooling() -> None:
    """Главный признак: на улице холоднее порога — дренаж замёрзнет, выключаем."""
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": -3.0, "is_winter": False}
    )
    dispatcher = FakeDispatcher()

    stopped = await _protection(adapter, dispatcher).check_once()

    assert stopped == [AC]
    assert len(dispatcher.sent) == 1
    intent = dispatcher.sent[0]
    assert intent.domain == "climate" and intent.service == "turn_off"
    assert intent.bypass_lockout is True, "правило безопасности не отменяется блокировкой"


@pytest.mark.asyncio
async def test_winter_flag_stops_cooling() -> None:
    """Флаг зимы выключает охлаждение и при тёплой улице."""
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": 12.0, "is_winter": True}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == [AC]


@pytest.mark.asyncio
async def test_warm_summer_is_left_alone() -> None:
    """Тепло и не зима — кондиционер не трогаем."""
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": 25.0, "is_winter": False}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_owner_gate_is_not_about_the_air_conditioner() -> None:
    """Гейт владельца защиту не касается (разъяснение владельца 2026-10-15).

    `ispolzovat_konditsioner` означает не «мёрзнет ли дренаж»: защита смотрит
    только мороз и зиму, поэтому тёплой улицей и выключенным гейтом охлаждение
    разрешено.
    """
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": 25.0, "is_winter": False}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_boundary_temperature_is_allowed() -> None:
    """Ровно на пороге охлаждать можно: запрет начинается ниже порога."""
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": 5.0, "is_winter": False}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []


@pytest.mark.asyncio
async def test_auto_mode_counts_as_cooling() -> None:
    """`heat_cool` может охлаждать сам — в мороз так же опасен, как `cool`."""
    adapter = FakeAdapter(
        modes={AC: "heat_cool"}, rules={"outside_temperature": -10.0, "is_winter": False}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == [AC]


@pytest.mark.asyncio
async def test_heating_is_not_touched() -> None:
    """Обогрев кондиционера защита не трогает: правило про охлаждение."""
    adapter = FakeAdapter(
        modes={AC: "heat"}, rules={"outside_temperature": -10.0, "is_winter": True}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_off_state_is_not_touched() -> None:
    """Выключенный кондиционер нечего выключать."""
    adapter = FakeAdapter(
        modes={AC: "off"}, rules={"outside_temperature": -10.0, "is_winter": True}
    )
    dispatcher = FakeDispatcher()

    assert await _protection(adapter, dispatcher).check_once() == []
    assert dispatcher.sent == []


@pytest.mark.asyncio
async def test_unknown_weather_does_not_stop_cooling() -> None:
    """Погода не прочитана (старт платформы) — прибор не трогаем.

    Условие автоматики при неизвестном сезоне охлаждать не разрешает (цена
    ошибки — испорченная техника). Но защита **выключает работающий прибор**,
    поэтому действует только на известный мороз: иначе после старта, пока
    значения не прочитаны, законно работающий кондиционер гас бы зря.
    """
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": None, "is_winter": None}
    )
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
async def test_state_change_triggers_check() -> None:
    """Изменение состояния кондиционера проверяется сразу, а не в следующий проход."""
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": -5.0, "is_winter": False}
    )
    dispatcher = FakeDispatcher()
    protection = _protection(adapter, dispatcher)

    await protection._on_state_change(  # noqa: SLF001 — обработчик подписки
        "state_change", {"entity_id": AC}
    )

    assert dispatcher.sent, "изменение состояния не запустило проверку"


@pytest.mark.asyncio
async def test_other_entity_does_not_trigger_check() -> None:
    """Чужие состояния защиту не будят."""
    adapter = FakeAdapter(
        modes={AC: "cool"}, rules={"outside_temperature": -5.0, "is_winter": False}
    )
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


def test_threshold_comes_from_the_manifest() -> None:
    """Порог температуры задаётся манифестом, а не зашит в код."""
    protection = _protection(FakeAdapter(), FakeDispatcher(), min_temp=3.5)

    assert protection.min_outside_temp == 3.5


@pytest.mark.asyncio
async def test_read_failure_is_named_as_blindness() -> None:
    """Сбой чтения — слепота защиты, и она названа (аудит 2026-10-16, К-4).

    Прежде защита молча пропускала проход: журнал видел строку WARNING, а снаружи
    служба выглядела работающей. Молчание кондиционера и молчание защиты значат
    разное — «нечего делать» против «не могу проверить».

    Returns:
        Ничего.
    """
    protection = AirConditionerProtection(
        adapter=FakeAdapter(fail=True), dispatcher=FakeDispatcher(), entities=[AC]
    )

    turned_off = await protection.check_once()

    assert turned_off == []
    assert protection.blind_reason is not None, "слепота защиты осталась незамеченной"
    assert protection.blind_count == 1


@pytest.mark.asyncio
async def test_empty_response_with_live_devices_is_blindness() -> None:
    """Пустой ответ дома при живых приборах — тоже слепота, а не тишина.

    Returns:
        Ничего.
    """
    protection = AirConditionerProtection(
        adapter=FakeAdapter(modes={}), dispatcher=FakeDispatcher(), entities=[AC]
    )

    await protection.check_once()

    assert protection.blind_reason is not None, "пустой ответ выдан за отсутствие приборов"


@pytest.mark.asyncio
async def test_sight_returns_after_a_failed_read() -> None:
    """После удачного чтения защита снова видит приборы.

    Returns:
        Ничего.
    """
    adapter = FakeAdapter(fail=True, modes={AC: "off"})
    protection = AirConditionerProtection(
        adapter=adapter, dispatcher=FakeDispatcher(), entities=[AC]
    )
    await protection.check_once()
    assert protection.blind_reason is not None

    adapter.fail = False
    await protection.check_once()

    assert protection.blind_reason is None, "защита осталась слепой после удачного чтения"


@pytest.mark.asyncio
async def test_blindness_is_not_repeated_in_the_journal(caplog: Any) -> None:
    """Долгая слепота не даёт строку на каждый проход (правило B67).

    Args:
        caplog: Захват записей журнала.

    Returns:
        Ничего.
    """
    import logging

    protection = AirConditionerProtection(
        adapter=FakeAdapter(fail=True), dispatcher=FakeDispatcher(), entities=[AC]
    )

    with caplog.at_level(logging.WARNING, logger="core.services.ac_protection"):
        await protection.check_once()
        await protection.check_once()
        await protection.check_once()

    warnings = [r for r in caplog.records if "слепа" in r.message]
    assert len(warnings) == 1, f"слепота повторилась в журнале {len(warnings)} раз"
    assert protection.blind_count == 3, "счётчик обязан видеть все проходы вслепую"
