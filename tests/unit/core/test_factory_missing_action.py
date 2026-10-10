"""Неизвестное действие проваливает загрузку, а не проходит молча (фаза 1, T005).

Ловушка фабрики (`research.md` D8): если имя действия не найдено в реестре,
печатается WARNING, `action_fn` остаётся `None`, переход проходит как
успешный — и **ничего не выполняет** (`factory.py:228-232`).

Для климата это особенно опасно: дом выглядит отапливаемым, а обогрев не
включается. Владелец видит «всё настроил, не работает» и ищет причину не там.

Ошибка в имени действия — это ошибка манифеста, а не предупреждение журнала.
Проверка уже существует, но собирает предупреждения вместо того, чтобы
останавливать загрузку (`factory.py:292-315`).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest

from core.definitions import YAMLFSMDefinition
from core.fsm.factory import FSMFactory
from core.registry import Registry


def _factory() -> FSMFactory:
    """Фабрика с полным реестром условий и действий.

    Returns:
        Фабрика, готовая к разбору определения.
    """
    from core.action_handlers import register_all_actions
    from core.guards.builtin import register_all_guards

    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    return FSMFactory(engine=None, registry=registry, event_bus=None)  # type: ignore[arg-type]


def _definition(action: str | None, guard: str | None = None) -> YAMLFSMDefinition:
    """Определение автомата с одним переходом.

    Args:
        action: Имя действия либо None.
        guard: Имя условия либо None.

    Returns:
        Модель определения.
    """
    transition: dict[str, object] = {
        "from_state": "OFF",
        "to_state": "ON",
        "trigger": "temperature_changed",
    }
    if action is not None:
        transition["action"] = action
    if guard is not None:
        transition["guard"] = guard

    return YAMLFSMDefinition.model_validate(
        {
            "entity_id": "switch.obogrevatel_kitchen_climate_control_10",
            "target_device_id": "switch.obogrevatel_kitchen",
            "initial_state": "OFF",
            "states": ["OFF", "ON"],
            "transitions": [transition],
        }
    )


class TestMissingActionFailsLoad:
    """Отсутствующее действие — ошибка загрузки."""

    def test_unknown_action_is_reported(self) -> None:
        """Действие не в реестре называется проверкой, а не теряется.

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(_definition("no_such_action"))  # noqa: SLF001

        assert any("no_such_action" in problem for problem in problems), (
            "проверка обязана назвать отсутствующее действие: иначе опечатка в "
            "имени проходит незамеченной, и переход молча ничего не делает"
        )

    def test_known_action_passes_validation(self) -> None:
        """Существующее действие проверку проходит.

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(_definition("heater_timer_on"))  # noqa: SLF001

        assert problems == [], f"существующее действие не должно считаться проблемой: {problems}"

    def test_transition_without_action_is_allowed(self) -> None:
        """Переход без действия — законен: так оформляют «ничего не менять».

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(_definition(action=None))  # noqa: SLF001

        assert problems == []

    def test_load_raises_on_unknown_action(self) -> None:
        """Сборка автомата прерывается, а не завершается «успешно».

        Returns:
            Ничего.
        """
        factory = _factory()

        with pytest.raises(Exception, match="no_such_action"):
            factory._yaml_to_fsm_definition(_definition("no_such_action"))  # noqa: SLF001

    def test_error_message_names_the_action(self) -> None:
        """Сообщение называет опечатку — по ней ищут за секунды.

        Returns:
            Ничего.
        """
        factory = _factory()

        with pytest.raises(Exception) as exc:
            factory._yaml_to_fsm_definition(_definition("heater_timer_on_typo"))  # noqa: SLF001

        assert "heater_timer_on_typo" in str(exc.value)

    def test_known_action_still_builds(self) -> None:
        """Существующее действие собирается как раньше.

        Returns:
            Ничего.
        """
        factory = _factory()

        definition = factory._yaml_to_fsm_definition(_definition("heater_timer_on"))  # noqa: SLF001

        assert definition.transitions[0].action is not None


class TestMissingGuardFailsLoad:
    """Отсутствующее условие — тоже ошибка загрузки."""

    def test_unknown_guard_is_reported(self) -> None:
        """Условие не в реестре называется проверкой.

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(  # noqa: SLF001
            _definition("heater_timer_on", guard="may_freeze")
        )

        assert any("may_freeze" in problem for problem in problems)

    def test_load_raises_on_unknown_guard(self) -> None:
        """Сборка прерывается на неизвестном условии.

        Returns:
            Ничего.
        """
        factory = _factory()

        with pytest.raises(Exception, match="may_freeze"):
            factory._yaml_to_fsm_definition(  # noqa: SLF001
                _definition("heater_timer_on", guard="may_freeze")
            )

    def test_known_guard_still_builds(self) -> None:
        """Существующее условие собирается как раньше.

        Returns:
            Ничего.
        """
        factory = _factory()

        definition = factory._yaml_to_fsm_definition(  # noqa: SLF001
            _definition("heater_timer_on", guard="may_heat")
        )

        assert definition.transitions[0].guard is not None
