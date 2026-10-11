"""Команды кондиционера: охлаждение на потолок и запрет зимой (US2).

Требования владельца: кондиционер зимой не включается никогда, в том числе
вручную — «я смотрел на статус, если вдруг включили с пульта, и выключал с
предупреждением через Яндекс-станцию». Поэтому у платформы есть команда
принудительного выключения, и она должна быть безусловной.

Переключение режима у кондиционера шумное (FR-016): режим меняется только при
фактическом изменении потребности, а не на каждое показание датчика.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any


AC = "climate.esphome_web_0d22a4_ac_name"


def _ctx(**params: Any) -> dict[str, Any]:
    """Контекст команды кондиционера.

    Args:
        **params: Ключи контекста.

    Returns:
        Словарь контекста.
    """
    context: dict[str, Any] = {"entity_id": AC}
    context.update(params)
    return context


class TestCoolCommand:
    """Охлаждение задаёт потолок комфорта."""

    def test_sets_temperature_to_ceiling(self) -> None:
        """Цель охлаждения — потолок комфорта.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        intent = ACTION_HANDLERS["ac_cool_on"](None, _ctx(comfort_max=25.0))

        assert intent is not None
        assert intent.domain == "climate"
        assert intent.service == "set_temperature"
        assert intent.data.get("temperature") == 25.0, (
            "охлаждать нужно до потолка, который назвал владелец: охлаждать "
            "«прохладнее» без его решения — значит перестудить дом"
        )
        assert intent.device_id == AC

    def test_without_ceiling_sends_nothing(self) -> None:
        """Без потолка комфорта команда не уходит.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        assert ACTION_HANDLERS["ac_cool_on"](None, _ctx()) is None, (
            "без потолка нечем задать цель: отправлять команду без цели — значит "
            "включить охлаждение на 16 °C по умолчанию устройства"
        )


class TestForcedOff:
    """Запрет кондиционера зимой — принудительное выключение."""

    def test_turns_off(self) -> None:
        """Команда выключения уходит.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        intent = ACTION_HANDLERS["ac_forced_off"](None, _ctx())

        assert intent is not None
        assert intent.service == "turn_off"

    def test_forced_off_bypasses_lockout(self) -> None:
        """Принудительное выключение обходит блокировку.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        intent = ACTION_HANDLERS["ac_forced_off"](None, _ctx(bypass_lockout=True))

        assert intent is not None
        assert intent.bypass_lockout is True, (
            "кондиционер, включённый зимой с пульта, надо выключить даже если "
            "платформа считает устройство занятым: включение зимой портит технику"
        )


class TestModeSwitching:
    """Режим переключается только при фактической смене потребности."""

    def test_mode_command_targets_climate(self) -> None:
        """Команда смены режима адресована кондиционеру.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        intent = ACTION_HANDLERS["ac_set_mode"](None, _ctx(hvac_mode="cool"))

        assert intent is not None
        assert intent.service == "set_hvac_mode"
        assert intent.data.get("hvac_mode") == "cool"

    def test_mode_without_value_sends_nothing(self) -> None:
        """Без режима команда не уходит.

        Returns:
            Ничего.
        """
        from core.action_handlers import ACTION_HANDLERS

        assert ACTION_HANDLERS["ac_set_mode"](None, _ctx()) is None
