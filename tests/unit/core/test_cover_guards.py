"""Условия штор: открыть или закрыть по флагам дома (спека 015).

Шторы датчиков не слушают: решение зависит только от флагов дома («мы спим»,
кто-то дома, дома собаки, разрешение закрывать ночью, авария) и роли шторы
(обычная или над дверью). Каждая ветка названа причиной, чтобы утренний разбор
отличал «не спим» от «пожарной безопасности» и «ночью закрывать не разрешено».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from core.guards.builtin import build_guards


def _guard(name: str) -> Any:
    """Взять условие по имени из реестра.

    Args:
        name: Имя условия.

    Returns:
        Функция ``(state, context) -> bool`` с ``deny_reason``.

    Raises:
        AssertionError: условия нет в реестре.
    """
    guards = build_guards(control_tracker=None)
    assert name in guards, f"условие `{name}` не зарегистрировано: {sorted(guards)}"
    return guards[name]


def _reason(guard: Any, context: dict[str, Any]) -> str | None:
    """Назвать причину отказа условия.

    Args:
        guard: Условие с ``deny_reason``.
        context: Контекст перехода.

    Returns:
        Имя причины либо ``None``.
    """
    return getattr(guard, "deny_reason", lambda *_: None)(None, context)


#: Обычная штора, кто-то дома, спим, ночью закрывать разрешено — ей пора закрыться.
_CLOSE = {
    "covers_enabled": True,
    "my_doma": True,
    "sobaki_doma": True,
    "cover_role": "regular",
    "sleep_modifier_on": True,
    "covers_close_night": True,
}


class TestCoversShouldClose:
    """Условие «штору пора закрыть» и причины отказа."""

    def test_should_close_when_sleeping_and_night_close_allowed(self) -> None:
        """Спим и разрешено закрывать ночью — закрываемся."""
        guard = _guard("covers_should_close")
        assert guard(None, dict(_CLOSE)) is True

    def test_should_not_close_when_awake(self) -> None:
        """Не спим — штора открыта."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "sleep_modifier_on": False}
        assert guard(None, context) is False
        assert _reason(guard, context) == "covers_stay_open"

    def test_should_not_close_when_night_close_disabled(self) -> None:
        """Спим, но владелец запретил закрывать ночью."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "covers_close_night": False}
        assert guard(None, context) is False
        assert _reason(guard, context) == "covers_night_close_off"

    def test_should_not_close_door_while_someone_home(self) -> None:
        """Штора над дверью не закрывается при людях — пожарная безопасность."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "cover_role": "door"}
        assert guard(None, context) is False
        assert _reason(guard, context) == "cover_fire_safety"

    def test_should_close_everything_when_nobody_home(self) -> None:
        """Никого и собак нет — закрывается всё, включая дверь."""
        guard = _guard("covers_should_close")
        context = {
            **_CLOSE,
            "my_doma": False,
            "sobaki_doma": False,
            "cover_role": "door",
            "sleep_modifier_on": False,
        }
        assert guard(None, context) is True

    def test_should_close_all_when_dogs_flag_unread(self) -> None:
        """Никого, про собак неизвестно — считаем, что их нет, закрываем всё."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "my_doma": False, "sobaki_doma": None}
        assert guard(None, context) is True

    def test_should_close_dogs_only_room_when_dogs_home(self) -> None:
        """Дома только собаки — спальня и кабинет закрываются."""
        guard = _guard("covers_should_close")
        context = {
            **_CLOSE,
            "my_doma": False,
            "sobaki_doma": True,
            "closes_when_dogs_only": True,
        }
        assert guard(None, context) is True

    def test_should_not_close_other_rooms_when_dogs_home(self) -> None:
        """Дома только собаки — остальные шторы не закрываются."""
        guard = _guard("covers_should_close")
        context = {
            **_CLOSE,
            "my_doma": False,
            "sobaki_doma": True,
            "closes_when_dogs_only": False,
        }
        assert guard(None, context) is False
        assert _reason(guard, context) == "covers_dogs_only"

    def test_my_doma_false_cancels_sleep_logic(self) -> None:
        """Никого нет — «мы спим» не решает: решает отсутствие людей."""
        guard = _guard("covers_should_close")
        context = {
            **_CLOSE,
            "my_doma": False,
            "sobaki_doma": False,
            "sleep_modifier_on": False,
        }
        assert guard(None, context) is True

    def test_emergency_blocks_closing(self) -> None:
        """Авария — закрывать нельзя, даже если обычно закрылись бы."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "cover_emergency": True}
        assert guard(None, context) is False
        assert _reason(guard, context) == "cover_emergency"

    def test_emergency_beats_disabled_feature(self) -> None:
        """Авария важнее выключенного фиче-флага дома."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "cover_emergency": True, "covers_enabled": False}
        assert guard(None, context) is False
        assert _reason(guard, context) == "cover_emergency"

    def test_feature_off_denies_with_reason(self) -> None:
        """Фиче-флаг выключен — платформа шторы не трогает, причина названа."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "covers_enabled": False}
        assert guard(None, context) is False
        assert _reason(guard, context) == "covers_disabled"

    def test_unknown_my_doma_counts_as_home(self) -> None:
        """Признак «кто-то дома» не прочитан — считаем, что люди дома."""
        guard = _guard("covers_should_close")
        context = {**_CLOSE, "my_doma": None, "cover_role": "door"}
        assert guard(None, context) is False
        assert _reason(guard, context) == "cover_fire_safety"


class TestCoversShouldOpen:
    """Условие «штору пора открыть» и причины отказа."""

    def test_should_open_when_close_not_needed(self) -> None:
        """Не спим — штору пора открыть."""
        guard = _guard("covers_should_open")
        context = {**_CLOSE, "sleep_modifier_on": False}
        assert guard(None, context) is True

    def test_should_not_open_when_should_close(self) -> None:
        """Пора закрывать — открывать нечего."""
        guard = _guard("covers_should_open")
        context = dict(_CLOSE)
        assert guard(None, context) is False
        assert _reason(guard, context) == "covers_stay_closed"

    def test_emergency_opens_even_with_feature_off(self) -> None:
        """Авария открывает шторы, игнорируя фиче-флаг."""
        guard = _guard("covers_should_open")
        context = {**_CLOSE, "cover_emergency": True, "covers_enabled": False}
        assert guard(None, context) is True

    def test_feature_off_denies_opening(self) -> None:
        """Фиче-флаг выключен — платформа шторы не трогает."""
        guard = _guard("covers_should_open")
        context = {**_CLOSE, "covers_enabled": False, "sleep_modifier_on": False}
        assert guard(None, context) is False
        assert _reason(guard, context) == "covers_disabled"

    def test_door_opens_even_when_sleeping(self) -> None:
        """Штора над дверью открыта, пока кто-то дома, даже если спим."""
        guard = _guard("covers_should_open")
        context = {**_CLOSE, "cover_role": "door"}
        assert guard(None, context) is True
