#!/usr/bin/env python3
"""Тесты для проверки удаления shadow mode из FSM."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.lighting.fsm import (
    light_fsm_definition,
    light_fsm_run,
    fsm_build_events,
    _LIGHT_FSM_STATE
)


def test_no_shadow_mode_in_lighting():
    """Проверка что lighting FSM не использует shadow mode."""
    # Очищаем состояние
    _LIGHT_FSM_STATE.clear()
    
    # Тестовая группа
    group = {
        "id": "test_group",
        "features": {"schedule": {}},
        "room": "test_room"
    }
    
    fsm_def = light_fsm_definition(group)
    
    # Проверяем что в определении FSM нет упоминаний shadow
    fsm_str = str(fsm_def)
    assert "shadow" not in fsm_str.lower(), "FSM definition содержит shadow"
    
    print("✅ Тест пройден: Shadow mode удалён из lighting FSM")


def test_fsm_executes_directly():
    """Проверка что FSM исполняется напрямую без shadow."""
    _LIGHT_FSM_STATE.clear()
    
    group = {
        "id": "test_exec",
        "features": {"motion": {}},
        "room": "test_room"
    }
    
    # Контекст с движением
    ctx = {
        "motion": True,
        "dark": True,
        "night": False,
        "schedule_on": False,
        "schedule_off": False,
        "party_mode": False,
        "away": False,
        "device_available": True
    }
    
    result = light_fsm_run(group, ctx)
    
    # Проверяем что результат содержит действие
    assert result is not None, "FSM не вернул результат"
    assert "action" in result, "Результат не содержит action"
    assert "state" in result, "Результат не содержит state"
    
    # Проверяем что нет флага shadow
    assert "shadow" not in result, "Результат содержит shadow"
    
    print("✅ Тест пройден: FSM исполняется напрямую")


def test_ui_no_shadow_toggle():
    """Проверка что UI не содержит переключатель shadow."""
    from features.lighting.ui import ui_fsm_status
    
    group = {"id": "test_ui"}
    gid = "test_ui"
    
    cards = ui_fsm_status(group, gid)
    
    # Преобразуем в строку для проверки
    cards_str = str(cards)
    
    # Проверяем что нет упоминаний shadow
    assert "shadow" not in cards_str.lower(), "UI содержит shadow режим"
    assert "fsm_shadow" not in cards_str, "UI содержит fsm_shadow entity"
    
    print("✅ Тест пройден: UI не содержит shadow toggle")


def test_helpers_no_shadow():
    """Проверка что helpers не создают fsm_shadow."""
    from features.lighting.helpers import group_feature_helpers, _feats_of
    
    group = {
        "id": "test_helpers",
        "features": {"schedule": {}}
    }
    
    helpers, _ = group_feature_helpers(group, "test_helpers", 0, {})
    
    # Проверяем что нет helper'а для fsm_shadow
    helper_names = [str(h.get("name", "")) for h in helpers]
    assert not any("shadow" in h.lower() for h in helper_names), \
        "Helpers содержат shadow"
    
    # Проверяем что есть fsm_enabled
    assert any("fsm" in h.lower() and "enabled" in h.lower() for h in helper_names), \
        "Helpers не содержат fsm_enabled: %s" % helper_names
    
    print("✅ Тест пройден: Helpers не создают fsm_shadow")


if __name__ == "__main__":
    print("🚀 Запуск тестов на удаление shadow mode...")
    
    test_no_shadow_mode_in_lighting()
    test_fsm_executes_directly()
    test_ui_no_shadow_toggle()
    test_helpers_no_shadow()
    
    print("\n🎉 Все тесты пройдены успешно! Shadow mode полностью удалён.")
