"""Ручной свет в режиме «мы спим» гаснет через 5 минут без движения.

Требование владельца 2026-10-21: если «мы спим» и кто-то включил свет в
санузле, его нужно выключить, когда движения не было 5 минут. Вне режима сна
остаётся прежний срок ручного оверрайда — 60 минут (`automation_rules
.lighting.manual_lockout_min`).

Здесь проверяются три части:

- условие «мы не спим» (`modifier_is_off`): неизвестное состояние считается
  «не спим», иначе пропавшая в HA сущность молча гасила бы свет через 5 минут;
- движок выбирает таймаут исходящего перехода по его условию на контексте
  состояния: при сне — короткий, вне сна — стандартный;
- шаблон `lighting.yaml` объявляет оба срока именно на `ON_MANUAL`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from core import FSMDefinition, FSMEngine, Transition
from core.guards.builtin import make_modifier_is_off


FSM_ID = "light.svet_v_sanuzle_lighting_10"
SLEEP_TIMEOUT_SEC = 300.0
MANUAL_TIMEOUT_SEC = 3600.0


def _sleep_definition(
    sleep_timeout: float = SLEEP_TIMEOUT_SEC,
    manual_timeout: float = MANUAL_TIMEOUT_SEC,
) -> FSMDefinition:
    """Автомат ручного света с двумя сроками по условию сна.

    Args:
        sleep_timeout: Короткий срок для проверки таймера (секунды).
        manual_timeout: Стандартный срок для проверки таймера (секунды).

    Returns:
        Описание автомата в форме `lighting.yaml`.
    """
    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="OFF",
        states=("OFF", "ON_MANUAL"),
        transitions=(
            Transition(from_state="OFF", to_state="ON_MANUAL", trigger="manual_switch_on"),
            Transition(
                from_state="ON_MANUAL",
                to_state="OFF",
                trigger="timeout",
                guard=make_modifier_is_off(),
                timeout_sec=manual_timeout,
            ),
            Transition(
                from_state="ON_MANUAL",
                to_state="OFF",
                trigger="timeout",
                guard=_sleep_is_on(),
                timeout_sec=sleep_timeout,
            ),
        ),
    )


def _sleep_is_on():
    """Условие «модификатор сна включён» — как `modifier_is_on` в реестре."""

    def modifier_is_on(state, context):
        del state
        return context.get("sleep_modifier_on") is True

    modifier_is_on.__name__ = "modifier_is_on"
    return modifier_is_on


class TestModifierIsOff:
    """Условие «мы не спим»."""

    def test_returns_true_when_modifier_is_off(self) -> None:
        """Модификатор выключен — свет живёт по стандартному сроку."""
        assert make_modifier_is_off()(None, {"sleep_modifier_on": False}) is True

    def test_returns_true_when_modifier_is_unknown(self) -> None:
        """Состояние не прочитано — не гасим свет через пять минут вслепую."""
        assert make_modifier_is_off()(None, {}) is True
        assert make_modifier_is_off()(None, {"sleep_modifier_on": None}) is True

    def test_returns_false_when_modifier_is_on(self) -> None:
        """Пока спим, действует короткий срок."""
        assert make_modifier_is_off()(None, {"sleep_modifier_on": True}) is False


class TestTimeoutChosenBySleepGuard:
    """Таймаут `ON_MANUAL` зависит от режима сна."""

    async def test_expected_timeout_is_five_minutes_while_asleep(self) -> None:
        """При сне сторож ждёт пять минут, а не час."""
        engine = FSMEngine()
        engine.register_definition(_sleep_definition(), restore_state=False)

        assert await engine.trigger(
            FSM_ID, "manual_switch_on", external_ctx={"sleep_modifier_on": True}
        )
        assert engine.get_state(FSM_ID).current_state == "ON_MANUAL"
        assert engine.expected_timeout_sec(FSM_ID) == SLEEP_TIMEOUT_SEC

    async def test_expected_timeout_is_hour_when_awake(self) -> None:
        """Вне сна остаётся стандартный ручной оверрайд — час."""
        engine = FSMEngine()
        engine.register_definition(_sleep_definition(), restore_state=False)

        assert await engine.trigger(
            FSM_ID, "manual_switch_on", external_ctx={"sleep_modifier_on": False}
        )
        assert engine.expected_timeout_sec(FSM_ID) == MANUAL_TIMEOUT_SEC

    async def test_expected_timeout_is_hour_when_modifier_unknown(self) -> None:
        """Неизвестный модификатор не сокращает срок до пяти минут."""
        engine = FSMEngine()
        engine.register_definition(_sleep_definition(), restore_state=False)

        assert await engine.trigger(FSM_ID, "manual_switch_on", external_ctx={})
        assert engine.expected_timeout_sec(FSM_ID) == MANUAL_TIMEOUT_SEC

    async def test_short_timer_fires_while_asleep(self) -> None:
        """Взведённый при сне таймер действительно гасит свет."""
        import asyncio

        engine = FSMEngine()
        engine.register_definition(
            _sleep_definition(sleep_timeout=0.05, manual_timeout=0.5),
            restore_state=False,
        )

        assert await engine.trigger(
            FSM_ID, "manual_switch_on", external_ctx={"sleep_modifier_on": True}
        )
        await asyncio.sleep(0.2)

        assert engine.get_state(FSM_ID).current_state == "OFF", "свет не погас через короткий срок"

    async def test_long_timer_waits_while_awake(self) -> None:
        """Вне сна короткий срок не срабатывает: действует стандартный."""
        import asyncio

        engine = FSMEngine()
        engine.register_definition(
            _sleep_definition(sleep_timeout=0.05, manual_timeout=0.5),
            restore_state=False,
        )

        assert await engine.trigger(
            FSM_ID, "manual_switch_on", external_ctx={"sleep_modifier_on": False}
        )
        await asyncio.sleep(0.2)

        assert engine.get_state(FSM_ID).current_state == "ON_MANUAL"


class TestTemplateDeclaresSleepTimeout:
    """Шаблон `lighting.yaml` объявляет оба срока именно на `ON_MANUAL`."""

    def test_lighting_template_has_sleep_and_manual_timeouts(self) -> None:
        """Переходы есть, сроки 300 и 3600, условия — modifier_is_on/off."""
        text = (
            Path(__file__).resolve().parents[3] / "src" / "features" / "lighting.yaml"
        ).read_text(encoding="utf-8")

        sleep_block = _transition_block(text, 'guard: "modifier_is_on"')
        manual_block = _transition_block(text, 'guard: "modifier_is_off"')

        assert 'from_state: "ON_MANUAL"' in sleep_block
        assert "timeout_sec: 300.0" in sleep_block
        assert 'from_state: "ON_MANUAL"' in manual_block
        assert "timeout_sec: 3600.0" in manual_block

    def test_lighting_template_extends_timer_on_motion(self) -> None:
        """Движение в ручном состоянии продлевает срок, а не отказывает."""
        text = (
            Path(__file__).resolve().parents[3] / "src" / "features" / "lighting.yaml"
        ).read_text(encoding="utf-8")

        for trigger in ("motion_detected", "motion_cleared"):
            block = _transition_block(
                text, f'trigger: "{trigger}"', marker='from_state: "ON_MANUAL"'
            )
            assert block, f"в ON_MANUAL нет перехода по {trigger}: событие кончится отказом"
            assert "timeout_sec: 300.0" in block


def _transition_block(text: str, anchor: str, marker: str | None = None) -> str:
    """Вырезать блок перехода, содержащий якорь.

    Args:
        text: Содержимое шаблона.
        anchor: Строка, которая обязана быть в блоке (условие или триггер).
        marker: Дополнительная строка, которую блок обязан содержать.

    Returns:
        Текст перехода либо пустая строка.
    """
    blocks = text.split("  - from_state:")
    for block in blocks[1:]:
        candidate = "  - from_state:" + block
        if anchor not in candidate:
            continue
        if marker is not None and marker not in candidate:
            continue
        return candidate
    return ""
