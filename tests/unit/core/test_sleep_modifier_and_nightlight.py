"""Ночью — яркого света нет, а вместо него ночник.

Два требования владельца, проверенные в боре 2026-10-09:

- **Пока «мы спим», яркий свет не включается нигде.** До этого санузел был в
  списке ночных комнат и включал свет в полную яркость ночью, то есть ровно то,
  что сбивает циркадные ритмы. Причина яркого света — в списке комнат, а ночь
  приходит сверху: из «модификатора мы спим», который включаете вы в Home
  Assistant.
- **Пока «мы спим», часть света работает ночником:** 3% яркости, красный
  (255, 0, 0), по движению, гаснет через 5 минут.

Ниже проверяется решение правила: из «спим» яркий свет не включается, ночник
включается, и решение не зависит от того, каким временем помечен ночной переход
(ночник работает и среди ночи, и утром, пока флаг стоит — это осознанно, флаг
значит «спим», а не «ночь»).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.guards.builtin import make_may_turn_on, make_modifier_is_on


HOUSE = ZoneInfo("Asia/Yekaterinburg")

#: Комната, где ночью яркий свет не нужен.
BATHROOM = "sanuzel"

#: Обычная комната.
LIVING = "gostinaia"

#: Три часа ночи — ночь и по часам, и по модификатору.
NIGHT = dt.datetime(2026, 10, 10, 3, 0, tzinfo=HOUSE)

#: Полдень.
DAY = dt.datetime(2026, 10, 10, 13, 0, tzinfo=HOUSE)


def _guard(at: dt.datetime = NIGHT) -> Any:
    """Условие «можно ли включать яркий свет» с зафиксированными часами.

    Args:
        at: Момент, который для условия считается «сейчас».

    Returns:
        Функция условия.
    """
    return make_may_turn_on(now=lambda _tz: at)


class TestSleepModifierStopsBrightLight:
    """Пока «мы спим», яркий свет не включается."""

    def test_bathroom_stays_dark_while_asleep(self) -> None:
        """Санузел ночью не отвечает на движение.

        Returns:
            Ничего.
        """
        guard = _guard()
        params = {"sleep_modifier_on": True, "night_motion_rooms": []}

        assert guard(None, {"room": BATHROOM, **params}) is False, (
            "санузел включил яркий свет, пока «мы спим»: это ровно то, что сбивает циркадные ритмы"
        )

    def test_every_room_stays_dark_while_asleep(self) -> None:
        """Список ночных комнат модификатор не отменяет.

        Returns:
            Ничего.
        """
        guard = _guard()

        for room in (BATHROOM, LIVING, "konteiner", "sad"):
            assert guard(None, {"room": room, "sleep_modifier_on": True}) is False, (
                f"комната {room} включила яркий свет, пока «мы спим»"
            )

    def test_while_awake_bathroom_works_by_motion(self) -> None:
        """Днём, когда «мы спим» выключено, санузел работает по движению.

        Returns:
            Ничего.
        """
        guard = _guard(DAY)

        assert (
            guard(None, {"room": BATHROOM, "sleep_modifier_on": False, "daylight": False}) is True
        )

    def test_without_modifier_evening_light_still_works(self) -> None:
        """Модификатора в доме нет — решение принимает солнце, как раньше.

        Returns:
            Ничего.
        """
        evening = dt.datetime(2026, 10, 10, 20, 0, tzinfo=HOUSE)
        guard = _guard(evening)

        assert guard(None, {"room": BATHROOM, "daylight": False}) is True, (
            "без модификатора санузел перестал включаться: отсутствие сущности в "
            "Home Assistant не должно молча гасить свет — вечером решает солнце"
        )

    def test_without_modifier_daylight_still_blocks(self) -> None:
        """День и без модификатора — свет не включается (датчиков нет, решает солнце).

        Returns:
            Ничего.
        """
        guard = _guard(DAY)

        assert guard(None, {"room": BATHROOM, "daylight": True}) is False, (
            "свет включился при дневном свете — жалоба владельца 2026-10-09 вернулась"
        )


class TestSleepModifierIsARealSwitch:
    """Состояние модификатора приходит из Home Assistant, а не из часов платформы."""

    def test_guard_reads_flag_from_context(self) -> None:
        """Условие ночника смотрит на признак из контекста события.

        Returns:
            Ничего.
        """
        guard = make_modifier_is_on()

        assert guard(None, {"sleep_modifier_on": True}) is True
        assert guard(None, {"sleep_modifier_on": False}) is False

    def test_missing_entity_means_awake(self) -> None:
        """Нет сущности — считаем, что не спим, и говорим об этом.

        Returns:
            Ничего.
        """
        guard = make_modifier_is_on()

        assert guard(None, {}) is False, (
            "отсутствующий модификатор принят за «мы спим»: свет в доме погас бы "
            "сам собой и никто не понял бы почему"
        )


class TestNightlightIsDimAndRed:
    """Ночник — это отдельное поведение, а не «тот же свет, но тусклее»."""

    def test_nightlight_action_asks_for_three_percent_red(self) -> None:
        """Команда ночника: 3% и красный.

        Returns:
            Ничего.
        """
        from core.action_handlers import turn_on_night_light

        intent = turn_on_night_light(None, {"entity_id": "light.svet_nad_stolom"})

        assert intent is not None
        assert intent.service == "turn_on"
        assert intent.data.get("brightness_pct") == 3, f"яркость ночника: {intent.data}"
        assert list(intent.data.get("rgb_color") or []) == [255, 0, 0], (
            f"цвет ночника: {intent.data}"
        )

    def test_nightlight_template_has_five_minute_timeout(self) -> None:
        """В шаблоне ночника стоит таймаут в 300 секунд.

        Returns:
            Ничего.
        """
        from pathlib import Path

        import yaml

        template = yaml.safe_load(Path("src/features/night_light.yaml").read_text(encoding="utf-8"))

        timeouts = [
            transition["timeout_sec"]
            for transition in template["transitions"]
            if transition["trigger"] == "timeout"
        ]

        assert timeouts == [300.0], f"таймауты ночника: {timeouts}"

    def test_nightlight_requires_sleep_modifier(self) -> None:
        """Включение ночника обусловлено модификатором, а не только движением.

        Returns:
            Ничего.
        """
        from pathlib import Path

        import yaml

        template = yaml.safe_load(Path("src/features/night_light.yaml").read_text(encoding="utf-8"))

        entry = next(
            t
            for t in template["transitions"]
            if t["trigger"] == "motion_detected" and t["from_state"] == "OFF"
        )

        assert entry.get("guard") == "modifier_is_on", (
            f"ночник включается без проверки «мы спим»: {entry}"
        )

    def test_nightlight_timeout_actually_turns_light_off(self) -> None:
        """По таймауту ночник выключает свет, а не только отпускает устройство.

        Returns:
            Ничего.
        """
        from pathlib import Path

        import yaml

        template = yaml.safe_load(Path("src/features/night_light.yaml").read_text(encoding="utf-8"))

        timeout = next(t for t in template["transitions"] if t["trigger"] == "timeout")

        assert timeout["action"] == "turn_off_night_light", (
            "таймаут заканчивается release_device: свет остаётся гореть — это "
            "был дефект прежнего шаблона"
        )


class TestModifierGovernsTheNight:
    """Ночью решает модификатор, а не часы платформы.

    Решение владельца 2026-10-09 (ответ на уточняющий вопрос): «свет по
    движению всегда, кроме периода мы спим». То есть при **известном**
    модификаторе ночное окно тишины не спрашивается: False — включаем, если
    темно; True — не включаем нигде. Окно и список ``night_motion_rooms``
    остаются фолбэком на случай, когда сущности в доме нет (None) — пропавшая
    в Home Assistant сущность не должна молча погасить свет.
    """

    def test_awake_at_night_motion_works_in_any_room(self) -> None:
        """«Мы спим» выключен — ночью по движению включаем везде, если темно.

        Returns:
            Ничего.
        """
        guard = _guard(NIGHT)
        context = {"room": LIVING, "sleep_modifier_on": False, "daylight": False}

        assert guard(None, context) is True, (
            "ночь, «мы спим» выключен, темно — а свет не включается: это "
            "окно тишины решило за модификатор, чего владелец не просил"
        )
        assert guard.deny_reason(None, context) is None  # type: ignore[attr-defined]

    def test_awake_but_bright_stays_dark(self) -> None:
        """Даже бодрствуя, светлое не зажигает свет — яркий свет среди дня не нужен.

        Returns:
            Ничего.
        """
        guard = _guard(NIGHT)
        context = {"room": LIVING, "sleep_modifier_on": False, "daylight": True}

        assert guard(None, context) is False
        assert guard.deny_reason(None, context) == "daylight", (  # type: ignore[attr-defined]
            "отказ «светло» обязан называться: без имени он выглядит как "
            "guard_failed — «условие отказало», из чего не понятно ничего"
        )

    def test_sleeping_keeps_denial_named(self) -> None:
        """«Мы спим» включён — отказ называется модификатором, а не ночью.

        Returns:
            Ничего.
        """
        guard = _guard(NIGHT)
        context = {"room": LIVING, "sleep_modifier_on": True}

        assert guard(None, context) is False
        assert guard.deny_reason(None, context) == "sleep_modifier"  # type: ignore[attr-defined]

    def test_without_entity_quiet_window_still_decides(self) -> None:
        """Сущности в доме нет — ночное окно работает как прежде.

        Returns:
            Ничего.
        """
        guard = _guard(NIGHT)
        context = {"room": LIVING, "daylight": False}

        assert guard(None, context) is False, (
            "без модификатора ночное окно перестало действовать: фолбэк потерян"
        )
        assert guard.deny_reason(None, context) == "quiet_hours"  # type: ignore[attr-defined]

    def test_without_entity_night_room_still_works(self) -> None:
        """Без модификатора ночные комнаты работают, как и раньше.

        Returns:
            Ничего.
        """
        guard = _guard(NIGHT)
        context = {"room": BATHROOM, "daylight": False, "night_motion_rooms": [BATHROOM]}

        assert guard(None, context) is True


class TestSleepStartedTurnsEverythingOff:
    """Включение «мы спим» гасит свет во всех состояниях автомата."""

    def test_lighting_template_covers_every_burning_state(self) -> None:
        """Шаблон гасит свет из любого состояния, где он может гореть.

        Returns:
            Ничего.
        """
        from pathlib import Path

        import yaml

        template = yaml.safe_load(Path("src/features/lighting.yaml").read_text(encoding="utf-8"))
        transitions = [t for t in template["transitions"] if t["trigger"] == "sleep_started"]

        by_state = {t["from_state"]: t for t in transitions}

        assert set(by_state) == {"OFF", "ON_MOTION", "ON_HOLD", "ON_MANUAL"}, (
            f"не все состояния гасятся по модификатору: {sorted(by_state)}"
        )
        for from_state, transition in by_state.items():
            assert transition["to_state"] == "OFF", f"{from_state}: {transition}"
            assert transition["action"] == "turn_off_light", (
                f"{from_state}: свет должен выключаться, а не отпускаться — {transition}"
            )

    def test_sleep_started_bypasses_manual_lockout(self) -> None:
        """Выключение по модификатору важнее локаута ручного действия.

        Returns:
            Ничего.
        """
        from core.fsm.engine import SAFETY_EVENTS

        assert "sleep_started" in SAFETY_EVENTS, (
            "без обхода локаута свет, включённый из приложения, продолжал бы гореть, пока все спят"
        )

    @pytest.mark.asyncio
    async def test_container_dispatches_to_automata_with_transition(self) -> None:
        """Доставка идёт только автоматам с переходом, по одному, без дебаунса.

        Returns:
            Ничего.
        """
        from core.services.day_cycle import deliver_to_automata

        delivered: list[tuple[str, str]] = []

        class FakeEngine:
            def entities_with_trigger(self, event: str) -> list[str]:
                assert event == "sleep_started"
                return ["light.svet_nad_stolom", "light.kitchen"]

            async def trigger(self, entity_id: str, event: str, *, respect_debounce: bool) -> None:
                assert respect_debounce is False, "событие модификатора не дребезг датчика"
                delivered.append((entity_id, event))

        await deliver_to_automata(FakeEngine(), "sleep_started", "Модификатор «мы спим»")  # type: ignore[arg-type]

        assert delivered == [
            ("light.svet_nad_stolom", "sleep_started"),
            ("light.kitchen", "sleep_started"),
        ], f"доставка: {delivered}"
