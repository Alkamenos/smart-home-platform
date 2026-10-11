"""Проверки единицы измерения таймера обогревателя и проверки доставки команды.

Живой дефект 2026-10-11: обогреватели дома вели себя как исправные — автомат
честно переключался ``IDLE → HEATING → IDLE``, сторож писал ``ok``, метрики
показывали работу, — но **ни один прибор в доме не грел**.

Причина в единице измерения. Таймер обогревателя в Home Assistant измеряется в
**секундах**:

.. code-block:: json

    "number.obogrevatel_spalnia_countdown": {"min": 0, "max": 43200,
                                              "unit_of_measurement": "s"}

а ``heater_timer_on`` отправлял ``run_minutes`` (=15) прямо в ``number.set_value``.
Home Assistant принимала значение и ставила **15 секунд** вместо пятнадцати минут:
прибор включался и гас через 15 секунд. Автомат при этом честно отрабатывал свой
таймер и выходил по ``timeout`` — то есть весь класс «механизм есть, выглядит
исправным, а команда не доходит» из спеки 010 US1.

Доказано прямым замером в доме: ``value: 3`` (как шлёт платформа) даёт таймер
``0`` и прибор не реагирует; ``value: 180`` (3 минуты в секундах) даёт
``180 s`` и обогреватель включается.

Вторая половина файла — страховка от повторения молчаливого отказа: команда,
применённая не к тому устройству или не в той единице, обязана быть замечена,
а не считаться успехом.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


RUN_MINUTES = 15
RUN_SECONDS = RUN_MINUTES * 60


def _action(name: str) -> Any:
    """Взять действие по имени из реестра.

    Args:
        name: Имя действия.

    Returns:
        Функция (state, context) -> CommandIntent.

    Raises:
        AssertionError: действия нет в реестре — шаблон его перехода отклонит.
    """
    assert name in ACTION_HANDLERS, (
        f"действие `{name}` не зарегистрировано: в реестре {sorted(ACTION_HANDLERS)}"
    )
    return ACTION_HANDLERS[name]


def _ctx(**params: Any) -> dict[str, Any]:
    """Контекст перехода климата.

    Args:
        params: Ключи контекста.

    Returns:
        Словарь контекста.
    """
    return params


class TestTimerUnitConversion:
    """Единица измерения таймера: минуты платформы против секунд устройства."""

    def test_seconds_timer_receives_seconds_not_minutes(self) -> None:
        """Таймер в секундах получает секунды — это и есть боевой дом.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        intent = action(
            None,
            _ctx(
                entity_id="switch.obogrevatel_spalnia",
                heater_timer="number.obogrevatel_spalnia_countdown",
                run_minutes=RUN_MINUTES,
                timer_unit="s",
            ),
        )
        timer_step = intent[-1]

        assert timer_step.data["value"] == RUN_SECONDS, (
            f"в таймер, измеряемый в секундах, ушло {timer_step.data.get('value')!r} "
            f"вместо {RUN_SECONDS}: Home Assistant примет это как 15 секунд, "
            "обогреватель включится и сразу выключится, а платформа будет "
            "считать, что отработала по таймеру"
        )

    def test_minutes_timer_still_receives_minutes(self) -> None:
        """Таймер в минутах не домножается: значение уходит как есть.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        steps = action(
            None,
            _ctx(
                entity_id="switch.obogrevatel_spalnia",
                heater_timer="number.obogrevatel_spalnia_countdown",
                run_minutes=RUN_MINUTES,
                timer_unit="min",
            ),
        )
        timer_step = steps[-1]

        assert timer_step.data["value"] == RUN_MINUTES, (
            f"в таймер, измеряемый в минутах, ушло {timer_step.data.get('value')!r} "
            f"вместо {RUN_MINUTES}: домножение на 60 здесь сделало бы работу "
            "часовой вместо получасовой"
        )

    def test_unknown_unit_falls_back_to_minutes_and_says_so(self) -> None:
        """Неизвестная единица — минуты, и решение видно в команде.

        Молчаливый выбор здесь опаснее неверного: без отметки в команде тот же
        баг вернётся на другом устройстве.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        steps = action(
            None,
            _ctx(
                entity_id="switch.obogrevatel_x",
                heater_timer="number.x_countdown",
                run_minutes=RUN_MINUTES,
                timer_unit="что-то неопознанное",
            ),
        )
        timer_step = steps[-1]

        assert timer_step.data["value"] == RUN_MINUTES
        assert timer_step.data.get("assumed_unit") == "min", (
            "единица не распознана, но в команде не сказано, что она угадана: "
            "следующая сессия не поймёт, откуда взялось это число"
        )

    def test_command_targets_timer_entity_not_the_switch(self) -> None:
        """Команда уходит таймеру, а не переключателю.

        Отдельная половина того же боевого дефекта: ``number.set_value`` для
        ``switch.obogrevatel_spalnia`` Home Assistant отвергает — это не сущность
        домена ``number``.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        steps = action(
            None,
            _ctx(
                entity_id="switch.obogrevatel_spalnia",
                heater_timer="number.obogrevatel_spalnia_countdown",
                run_minutes=RUN_MINUTES,
                timer_unit="s",
            ),
        )
        timer_step = steps[-1]

        assert timer_step.device_id == "number.obogrevatel_spalnia_countdown", (
            f"команда домена `number` ушла на {timer_step.device_id!r}: Home "
            "Assistant не найдёт такой сущности в домене `number` и откажет — "
            "при этом платформа сочтёт команду отправленной"
        )


class TestTimerUnitIsDiscoveredFromHomeAssistant:
    """Единица не выдумывается платформой, а читается у устройства."""

    def test_adapter_reports_seconds_timer(self) -> None:
        """Адаптер отдаёт единицу таймера, прочитанную из Home Assistant.

        Returns:
            Ничего.
        """
        from adapters.ha_adapter import HAAdapter

        assert hasattr(HAAdapter, "get_entity_unit"), (
            "у адаптера нет способа узнать единицу измерения сущности: без неё "
            "платформа вынуждена угадывать и угадывает неверно — именно так "
            "обогрев молчал сутки"
        )

    def test_adapter_remembers_unit_read_at_startup(self) -> None:
        """Единица, прочитанная при старте, доступна без обращения к сети.

        Единицу нужно знать на пути действия, а действие вызывается на каждом
        решении. Обращение к Home Assistant из условия означало бы запрос в сети
        на каждое показание датчика — или, что хуже, отказ при обрыве связи.

        Returns:
            Ничего.
        """
        from adapters.ha_adapter import HAAdapter

        adapter = HAAdapter.__new__(HAAdapter)
        adapter._entity_units = {}
        remember = getattr(adapter, "remember_entity_unit", None)
        assert callable(remember), (
            "адаптер не умеет запоминать прочитанную единицу: без этого каждое "
            "включение обогревателя требовало бы запроса в Home Assistant"
        )
        remember("number.obogrevatel_spalnia_countdown", "s")
        assert adapter._entity_units["number.obogrevatel_spalnia_countdown"] == "s"

    def test_behavior_params_carry_unit_to_the_action(self) -> None:
        """Единица, объявленная в манифесте, доходит до действия без правок кода.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        steps = ACTION_HANDLERS["heater_timer_on"](
            None,
            _ctx(
                entity_id="switch.obogrevatel_x",
                heater_timer="number.x_countdown",
                run_minutes=RUN_MINUTES,
                timer_unit="s",
            ),
        )
        assert steps[-1].data["value"] == RUN_SECONDS, (
            "объявленная в манифесте единица не дошла до команды: параметр "
            "поведения читается, но в намерение не попадает"
        )
