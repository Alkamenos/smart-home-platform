"""Путь данных от Home Assistant до действия обогрева.

За день в бою вскрылось четыре разрыва подряд, и все они были одного класса:
значение **прочитано**, но **не дошло**. Проверялось чтение — и оно было
исправным; проверялось дохождение — и оно оказывалось пустым:

1. ``_event_context()`` не вызывался ни разу: уставка, сезон и потолок
   комфорта терялись по дороге к решению, ``may_heat`` получал «данных нет» и
   отказывал при любой температуре. Уставка 30 °C не включила ни одного
   обогревателя.
2. Единица измерения таймера читалась у 5 приборов при старте, но в действие
   приходил ``None`` — и платформа угадывала минуты для секундного таймера.
3. Адресатом команды был ``switch.*`` при домене ``number``: Home Assistant
   отвергал команду, а платформа считала её отправленной.
4. Проверка состояния смотрела на таймер (у него состояние «сколько осталось»)
   вместо обогревателя: ``on`` требовалось, а читался ``0``.

Общий класс: каждая половина по отдельности выглядела исправной. Поэтому
проверки здесь смотрят на **оба конца сразу** — значение прочитано **и** дошло
до действия, которое примет решение.

Боевой дефект 2026-10-11, спека 014, T024.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from adapters.ha_adapter import HAAdapter
from core.action_handlers import ACTION_HANDLERS


RUN_MINUTES = 15
RUN_SECONDS = RUN_MINUTES * 60

HEATER = "switch.obogrevatel_spalnia"
TIMER = "number.obogrevatel_spalnia_countdown"


def _adapter(**attrs: Any) -> HAAdapter:
    """Адаптер с заданными атрибутами и без сети.

    Args:
        attrs: Атрибуты, которые нужно выставить.

    Returns:
        Готовый адаптер.
    """
    adapter = HAAdapter.__new__(HAAdapter)
    adapter._entity_units = {}
    adapter._manifest = None
    adapter._ws_client = None
    for name, value in attrs.items():
        setattr(adapter, name, value)
    return adapter


class TestTimerUnitReachesTheAction:
    """Единица измерения, прочитанная у прибора, доходит до команды."""

    def test_unit_read_from_ha_becomes_timer_unit_in_event_context(self) -> None:
        """Прочитанная единица видна в контексте события под своим именем.

        Returns:
            Ничего.
        """
        adapter = _adapter()
        adapter.remember_entity_unit(TIMER, "s")
        adapter.heater_timer_of = {HEATER: TIMER}

        context = HAAdapter._event_context(adapter, HEATER)

        assert context.get("timer_unit") == "s", (
            "единица таймера прочитана у прибора, но не дошла до контекста "
            "решения: действие получит None, угадает минуты и отправит 15 "
            "вместо 900 секунд — обогреватель включится и сразу выключится, "
            "а платформа покажет исправную работу"
        )

    def test_action_converts_minutes_to_seconds_with_that_unit(self) -> None:
        """Единица из контекста превращает минуты в секунды в самой команде.

        Returns:
            Ничего.
        """
        adapter = _adapter()
        adapter.remember_entity_unit(TIMER, "s")
        adapter.heater_timer_of = {HEATER: TIMER}
        context = {**HAAdapter._event_context(adapter, HEATER), "entity_id": HEATER}

        steps = ACTION_HANDLERS["heater_timer_on"](
            None,
            {
                **context,
                "heater_timer": TIMER,
                "run_minutes": RUN_MINUTES,
            },
        )

        assert steps[-1].data["value"] == RUN_SECONDS, (
            f"в секундный таймер ушло {steps[-1].data.get('value')!r} вместо "
            f"{RUN_SECONDS}: единица не дошла до действия, и платформа "
            "угадала минуты"
        )
        assert "assumed_unit" not in steps[-1].data, (
            "единица помечена как угаданная, хотя она прочитана у прибора: "
            "оператор увидит в журнале ложное предупреждение и перестанет "
            "верить таким сообщениям вообще"
        )


class TestStateEntityIsTheHeaterNotTheTimer:
    """Проверка состояния смотрит на обогреватель, а не на таймер."""

    def test_timer_step_checks_the_heater(self) -> None:
        """Шаг с таймером ждёт включения обогревателя, а не таймера.

        Returns:
            Ничего.
        """
        steps = ACTION_HANDLERS["heater_timer_on"](
            None,
            {
                "entity_id": HEATER,
                "heater_timer": TIMER,
                "run_minutes": RUN_MINUTES,
                "timer_unit": "s",
            },
        )

        timer_step = steps[-1]
        assert timer_step.state_entity == HEATER, (
            f"шаг с таймером проверяет состояние {timer_step.state_entity!r}: "
            "у таймера состояние — «сколько секунд осталось», то есть 0 и у "
            "включённого прибора. Проверка отклонит команду включения, хотя "
            "обогреватель только что включился (в бою 2026-10-11 так и вышело)"
        )

    def test_off_step_needs_no_state_gate(self) -> None:
        """Выключение не проверяет состояние: чтобы гасить, прибор включён.

        Returns:
            Ничего.
        """
        steps = ACTION_HANDLERS["heater_off"](None, {"entity_id": HEATER, "heater_timer": TIMER})

        for step in steps:
            assert step.requires_state is None, (
                f"шаг {step.service} требует состояния {step.requires_state!r}: "
                "чтобы выключить прибор, он должен быть включён. Такое "
                "требование делает команду неотправляемой — включённый прибор "
                "остался бы греться (в бою 2026-10-11 так и вышло)"
            )
