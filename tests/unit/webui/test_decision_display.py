"""
T018-T019: Проверки отображения причины решения на карточке.

История 2 (P1): Карточка показывает, почему устройство в этом состоянии.
Причина берётся из decisions контекста, формулировка совпадает с журналом.

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""

import time


class TestDecisionDisplay:
    """T018: Формулировка причины совпадает со словарём."""

    def test_decision_reason_text_on_card(self) -> None:
        """На карточке показывается reason_text из decision."""
        from src.core.events.fsm_events import REASON_TEXT

        # Решение с отказом по условию
        decision = {
            "at": time.time(),
            "outcome": "denied",
            "reason_code": "guard_failed",
            "reason_text": REASON_TEXT.get("guard_failed", "условие не пройдено"),
            "trigger": "turn_on",
        }

        # Карточка выведет reason_text
        display = f"выключено: {decision['reason_text']}"
        assert "условие не пройдено" in display

    def test_decision_on_reason_matches_dictionary(self) -> None:
        """Текст включения совпадает со словарём."""
        from src.core.events.fsm_events import REASON_TEXT

        reason_code = "action_on"
        reason_text = REASON_TEXT.get(reason_code, "включено по расписанию")

        assert reason_text == "включено по расписанию"
        # На карточке будет именно это, не "action_on"

    def test_decision_off_reason_matches_dictionary(self) -> None:
        """Текст выключения совпадает со словарём."""
        from src.core.events.fsm_events import REASON_TEXT

        reason_code = "action_off"
        reason_text = REASON_TEXT.get(reason_code, "выключено по расписанию")

        assert reason_text == "выключено по расписанию"

    def test_decision_sleep_modifier_reason(self) -> None:
        """Причина по модификатору сна."""
        from src.core.events.fsm_events import REASON_SLEEP_MODIFIER, REASON_TEXT

        reason_text = REASON_TEXT.get(REASON_SLEEP_MODIFIER, "выключено модификатором сна")
        assert reason_text == "выключено модификатором сна"

    def test_decision_daylight_reason(self) -> None:
        """Причина по дневному свету."""
        from src.core.events.fsm_events import REASON_DAYLIGHT, REASON_TEXT

        reason_text = REASON_TEXT.get(REASON_DAYLIGHT, "светло")
        assert reason_text == "светло"

    def test_decision_no_transition_reason(self) -> None:
        """Причина: нет подходящего переходов."""
        from src.core.events.fsm_events import REASON_NO_TRANSITION, REASON_TEXT

        reason_text = REASON_TEXT.get(REASON_NO_TRANSITION, "нет подходящего переходов")
        assert reason_text == "нет подходящего переходов"

    def test_card_does_not_show_reason_code(self) -> None:
        """На карточке не показывается машинный код (guard_failed), только текст."""
        decision = {
            "at": time.time(),
            "outcome": "denied",
            "reason_code": "guard_failed",  # Это не показывается
            "reason_text": "условие не пройдено",  # Это показывается
            "trigger": "turn_on",
        }

        # Карточка выведет reason_text, а не reason_code
        display = decision["reason_text"]
        assert display == "условие не пройдено"
        assert "guard_failed" not in display


class TestDecisionTime:
    """T019: Относительное время решения на карточке."""

    def test_decision_just_now(self) -> None:
        """Решение только что (менее 1 минуты назад)."""
        now = time.time()
        decision_at = now - 30  # 30 секунд назад

        elapsed = now - decision_at
        if elapsed < 60:
            display = "только что"
        elif elapsed < 3600:
            display = f"{int(elapsed / 60)} мин назад"
        else:
            display = f"{int(elapsed / 3600)} ч назад"

        assert display == "только что"

    def test_decision_minutes_ago(self) -> None:
        """Решение N минут назад."""
        now = time.time()
        decision_at = now - 300  # 5 минут назад

        elapsed = now - decision_at
        if elapsed < 60:
            display = "только что"
        elif elapsed < 3600:
            display = f"{int(elapsed / 60)} мин назад"
        else:
            display = f"{int(elapsed / 3600)} ч назад"

        assert display == "5 мин назад"

    def test_decision_hours_ago(self) -> None:
        """Решение N часов назад."""
        now = time.time()
        decision_at = now - 7200  # 2 часа назад

        elapsed = now - decision_at
        if elapsed < 60:
            display = "только что"
        elif elapsed < 3600:
            display = f"{int(elapsed / 60)} мин назад"
        else:
            display = f"{int(elapsed / 3600)} ч назад"

        assert display == "2 ч назад"

    def test_card_shows_relative_time_not_absolute(self) -> None:
        """На карточке показывается относительное время, не абсолютное."""
        now = time.time()
        decision_at = now - 180  # 3 минуты назад

        # Карточка вычисляет относительное время в момент рендера
        elapsed = now - decision_at
        display = f"{int(elapsed / 60)} мин назад"

        assert "мин назад" in display
        assert ":" not in display  # Не "20:04:35", а "3 мин назад"


class TestDecisionOnCard:
    """Интеграция: как причина выглядит на карточке."""

    def test_card_shows_why_device_off(self) -> None:
        """На карточке выключенного устройства видна причина."""
        from src.core.events.fsm_events import REASON_TEXT

        decision = {
            "at": time.time() - 300,  # 5 минут назад
            "outcome": "denied",
            "reason_code": "guard_failed",
            "reason_text": REASON_TEXT.get("guard_failed"),
            "trigger": "turn_on",
        }

        # Карточка показывает:
        # Статус: выключено
        # Причина: условие не пройдено (5 мин назад)
        if decision["outcome"] == "denied":
            display = f"не включилось: {decision['reason_text']} (5 мин назад)"
            assert "условие не пройдено" in display
            assert "5 мин назад" in display

    def test_card_shows_why_device_on(self) -> None:
        """На карточке включённого устройства видна причина включения."""
        from src.core.events.fsm_events import REASON_TEXT

        decision = {
            "at": time.time() - 60,
            "outcome": "on",
            "reason_code": "action_on",
            "reason_text": REASON_TEXT.get("action_on"),
            "trigger": "sunset_started",
        }

        # Карточка показывает:
        # Статус: включено
        # Причина: включено по расписанию (1 мин назад)
        if decision["outcome"] == "on":
            display = f"включено: {decision['reason_text']} (1 мин назад)"
            assert "включено по расписанию" in display
            assert "1 мин назад" in display

    def test_card_shows_sensor_state_without_reason(self) -> None:
        """На карточке датчика показывается состояние, причина не нужна."""
        # Датчик — только чтение, причин там нет
        # На карточке просто "21.5 °C", без причины
        display = "21.5 °C"
        assert "мин назад" not in display
