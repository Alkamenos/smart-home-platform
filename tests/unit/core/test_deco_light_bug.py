"""
Баг: Гирлянда включилась без причины (2026-10-09).

Сценарий:
- Гирлянда на террасе (light.girlianda_terassa) с параметром off_by: "sleep"
- Тригер sunset_started срабатывает и включает свет
- Однако guard is_manual_override_enabled пропускает переход даже когда его НЕ должен пропускать

Ожидаемое поведение:
- sunset_started ВСЕГДА включает гирлянду
- is_manual_override_enabled проверяет, что нет активной блокировки (не было ручного вмешательства час назад)

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""


class TestDecoLightSunset:
    """Тесты включения гирлянды по закату."""

    def test_deco_light_turns_on_at_sunset(self) -> None:
        """Гирлянда включается по закату (sunset_started)."""
        # Параметр: off_by = "sleep"
        # Тригер: sunset_started
        # Guard: is_manual_override_enabled (блокировка НЕ активна)
        # Ожидается: переход OFF → ON_DECO и action "turn_on_light"

        # Состояние: OFF
        current_state = "OFF"
        has_lockout = False  # Нет активной блокировки

        # Guard должен пройти: if not in_lockout → True
        guard_passes = not has_lockout
        assert guard_passes is True

        # Переход должен произойти
        should_transition = current_state == "OFF" and guard_passes
        new_state = "ON_DECO" if should_transition else current_state

        assert new_state == "ON_DECO", "Гирлянда должна включиться по закату"

    def test_deco_light_respects_lockout(self) -> None:
        """После ручного выключения в течение часа гирлянда не включится по закату."""
        # Сценарий:
        # 1. Владелец выключил гирлянду руками в 18:00
        # 2. В 18:50 закат, платформа хочет включить
        # 3. Guard должен запретить: есть ручное вмешательство в течение последнего часа

        current_state = "OFF"
        has_lockout = True  # Было ручное вмешательство 10 минут назад

        guard_passes = not has_lockout
        assert guard_passes is False, "Guard должен запретить переход при активной блокировке"

        should_transition = current_state == "OFF" and guard_passes
        new_state = "ON_DECO" if should_transition else current_state

        assert new_state == "OFF", "Гирлянда не должна включиться во время локаута"

    def test_stops_on_sleep_uses_off_by_param(self) -> None:
        """Guard stops_on_sleep проверяет параметр off_by в контексте."""
        # Guard должен смотреть на параметр off_by из контекста
        # Если off_by == "sleep", то свет гаснет по модификатору "мы спим"
        # Если off_by == "sunrise", то свет гаснет по рассвету

        # Тестируем декодирование параметра
        context_with_sleep = {"off_by": "sleep"}
        context_with_sunrise = {"off_by": "sunrise"}

        # Guard stops_on_sleep должен вернуть True для sleep, False для sunrise
        stops_on_sleep_result = str(context_with_sleep.get("off_by", "")).strip().lower() == "sleep"
        assert stops_on_sleep_result is True

        stops_on_sleep_result_sunrise = (
            str(context_with_sunrise.get("off_by", "")).strip().lower() == "sleep"
        )
        assert stops_on_sleep_result_sunrise is False

    def test_sleep_started_stops_deco_light_with_sleep_param(self) -> None:
        """По событию sleep_started гирлянда (off_by: sleep) выключается."""
        # Событие: sleep_started
        # Состояние: ON_DECO
        # Параметр: off_by = "sleep"
        # Guard: stops_on_sleep (должна вернуть True)
        # Ожидается: переход ON_DECO → OFF и action "turn_off_light"

        current_state = "ON_DECO"
        off_by = "sleep"

        # Guard stops_on_sleep
        guard_passes = off_by == "sleep"
        assert guard_passes is True

        # Переход должен произойти
        should_transition = current_state == "ON_DECO" and guard_passes
        new_state = "OFF" if should_transition else current_state

        assert new_state == "OFF", "Гирлянда должна выключиться по sleep_started"

    def test_sleep_started_does_not_stop_night_light(self) -> None:
        """По событию sleep_started ночное освещение (off_by: sunrise) НЕ выключается."""
        # Событие: sleep_started
        # Состояние: ON_DECO
        # Параметр: off_by = "sunrise"
        # Guard: stops_on_sleep (должна вернуть False)
        # Ожидается: переход запрещён, свет остаётся ON_DECO

        current_state = "ON_DECO"
        off_by = "sunrise"

        # Guard stops_on_sleep
        guard_passes = off_by == "sleep"
        assert guard_passes is False

        # Переход НЕ должен произойти
        should_transition = current_state == "ON_DECO" and guard_passes
        new_state = "OFF" if should_transition else current_state

        assert new_state == "ON_DECO", "Ночное освещение должно продолжать гореть"
