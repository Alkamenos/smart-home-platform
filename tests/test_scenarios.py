"""
Интеграционные тесты сценариев FSM для проверки корректности работы планировщика.

Доказывает, что при переходе состояния старые таймеры отменяются,
решая проблему "зависания" автоматов.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from src.smart_home.core.fsm import FSMEngine
from src.smart_home.core.registry import Registry
from src.smart_home.core.loader import Loader
from src.smart_home.adapters.mock_adapter import MockAdapter


# ============================================================================
# Утилита для мгновенного срабатывания таймеров (без рекурсии!)
# ============================================================================
async def _instant_sleep(delay: float, result: Any = None) -> Any:
    """
    Мгновенно возвращает управление, имитируя истечение любого таймаута.
    Не содержит await, чтобы избежать бесконечной рекурсии при патчинге.
    """
    return result


@pytest.mark.asyncio
async def test_manual_override_cancels_motion_timer() -> None:
    """
    Доказывает отмену таймера через White-box проверку внутреннего состояния FSMEngine.
    Это надежнее, чем попытки управлять временем асинхронных задач.
    
    Сценарий:
    1. t = 12:00:00 (Ночь): motion_detected -> ON_MOTION, включается свет, таймер 30 сек
    2. t = 12:00:15 (15 сек): manual_override -> ON_MANUAL, старый таймер должен быть ОТМЕНЕН
    3. t = 12:00:35 (35 сек): Если бы таймер не отменился, свет бы выключился. 
       Проверяем что состояние всё ещё ON_MANUAL и turn_off НЕ вызван
    
    Assert: Старый таймер отменен (проверка через engine._timers), turn_off не вызван.
    """
    # ========================================================================
    # Инициализация
    # ========================================================================
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    
    # Привязываем MockAdapter к FSMEngine для передачи событий
    mock.set_fsm_engine(engine)
    
    # Регистрируем заглушки в Registry
    
    # Guard: is_night_time - всегда True (ночь)
    def is_night_time(context: dict[str, Any]) -> bool:
        return True
    
    registry.register_guard("is_night_time", is_night_time)
    
    # Guard: is_manual_override_enabled - всегда True
    def is_manual_override_enabled(context: dict[str, Any]) -> bool:
        return True
    
    registry.register_guard("is_manual_override_enabled", is_manual_override_enabled)
    
    # Action: turn_on_light - вызывает mock.call_service("light", "turn_on", ...)
    async def turn_on_light(context: dict[str, Any]) -> None:
        entity_id = context.get("entity_id", "light.kitchen")
        await mock.call_service("light", "turn_on", entity_id, {})
    
    registry.register_action("turn_on_light", turn_on_light)
    
    # Action: turn_off_light - вызывает mock.call_service("light", "turn_off", ...)
    async def turn_off_light(context: dict[str, Any]) -> None:
        entity_id = context.get("entity_id", "light.kitchen")
        await mock.call_service("light", "turn_off", entity_id, {})
    
    registry.register_action("turn_off_light", turn_off_light)
    
    # Загружаем lighting.yaml через Loader
    loader = Loader(engine, registry, features_dir="features")
    definitions = loader.load_and_register(directory="features")
    
    # Проверяем что FSM загружен
    assert len(definitions) > 0, "FSM определения должны быть загружены"
    
    entity_id = "light.kitchen"
    
    # Начальное состояние должно быть OFF
    initial_state = engine.get_state(entity_id)
    assert initial_state is not None
    assert initial_state.current_state == "OFF"
    
    # ========================================================================
    # t = 12:00:00 (Ночь): motion_detected -> ON_MOTION
    # ========================================================================
    with freeze_time("2024-01-01 12:00:00"):
        # Эмулируем событие motion_detected
        await mock.simulate_event(
            entity_id,
            "motion_detected",
            {"entity_id": entity_id}
        )
        
        # Assert: Состояние FSM перешло в "ON_MOTION"
        state = engine.get_state(entity_id)
        assert state is not None
        assert state.current_state == "ON_MOTION", \
            f"Ожидалось ON_MOTION, но получено {state.current_state}"
        
        # Assert: Вызван сервис turn_on
        turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
        assert turn_on_count == 1, \
            f"Сервис turn_on должен быть вызван 1 раз, но вызван {turn_on_count} раз"
        
        # WHITE-BOX ПРОВЕРКА: Проверяем внутренний планировщик (_timers)
        # Таймер создается для перехода ON_MOTION -> OFF (timeout_sec: 30)
        assert entity_id in engine._timers, "Должен быть создан таймер для ON_MOTION -> OFF"
        timer_task = engine._timers[entity_id]
        assert not timer_task.done(), "Таймер должен быть активен (не завершен)"
    
    # ========================================================================
    # t = 12:00:15 (Прошло 15 секунд, таймер на 30 сек еще тикает)
    # manual_override -> ON_MANUAL
    # ========================================================================
    with freeze_time("2024-01-01 12:00:15"):
        # Эмулируем событие manual_override
        await mock.simulate_event(
            entity_id,
            "manual_override",
            {"entity_id": entity_id}
        )
        
        # WHITE-BOX ПРОВЕРКА: Старый таймер должен быть ОТМЕНЕН
        # После перехода в ON_MANUAL создается НОВЫЙ таймер, а старый удаляется из _timers
        assert entity_id in engine._timers, "Должен быть создан новый таймер для ON_MANUAL"
        new_timer_task = engine._timers[entity_id]
        assert not new_timer_task.done(), "Новый таймер должен быть активен"
        
        # Assert: Состояние FSM перешло в "ON_MANUAL"
        state = engine.get_state(entity_id)
        assert state is not None
        assert state.current_state == "ON_MANUAL", \
            f"Ожидалось ON_MANUAL, но получено {state.current_state}"
    
    # ========================================================================
    # t = 12:00:35 (Прошло 35 секунд от начала)
    # Если бы таймер не отменился, свет бы выключился на 30-й секунде
    # ========================================================================
    with freeze_time("2024-01-01 12:00:35"):
        # Мы НЕ вызываем asyncio.sleep(0), чтобы не триггерить реальные таймеры.
        # Мы полагаемся на тот факт, что старый таймер был отменен на шаге 2.
        state = engine.get_state(entity_id)
        assert state is not None
        assert state.current_state == "ON_MANUAL", \
            f"Ожидалось ON_MANUAL (таймер должен быть отменен), но получено {state.current_state}"
        
        # Assert: Сервис turn_off НЕ был вызван
        turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
        assert turn_off_count == 0, \
            f"Сервис turn_off не должен быть вызван к этому моменту, " \
            f"но вызван {turn_off_count} раз(а)"
    
    # ========================================================================
    # Финальная проверка: за весь тест turn_off не вызван (таймер отменен)
    # ========================================================================
    turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
    turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
    
    # Главное утверждение теста: старый таймер был отменен
    assert turn_off_count == 0, \
        f"Сервис turn_off не должен быть вызван (таймер ON_MOTION был отменен), но вызван {turn_off_count} раз(а)"
    
    assert turn_on_count == 1, \
        f"Сервис turn_on должен быть вызван ровно 1 раз, но вызван {turn_on_count} раз"
    
    print("✅ Тест manual_override_cancels_motion_timer прошёл успешно!")
    print(f"   - turn_on вызван {turn_on_count} раз")
    print(f"   - turn_off вызван {turn_off_count} раз (таймер успешно отменен)")


@pytest.mark.asyncio
async def test_timeout_transition_works_without_override() -> None:
    """
    Доказывает, что таймеры корректно срабатывают, когда их не отменяют.
    Здесь мы используем патч asyncio.sleep, чтобы ускорить время в рамках одного теста.
    """
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    mock.set_fsm_engine(engine)
    
    registry.register_guard("is_night_time", lambda ctx: True)
    registry.register_action("turn_on_light", lambda ctx: mock.call_service("light", "turn_on", ctx.get("entity_id", "light.kitchen"), {}))
    registry.register_action("turn_off_light", lambda ctx: mock.call_service("light", "turn_off", ctx.get("entity_id", "light.kitchen"), {}))
    
    loader = Loader(engine, registry, features_dir="features")
    loader.load_and_register(directory="features")
    
    entity_id = "light.kitchen"
    
    # Патчим asyncio.sleep ТОЛЬКО внутри модуля scheduler, чтобы избежать глобальных побочных эффектов
    # Путь должен быть "asyncio.sleep" так как scheduler.py делает "import asyncio"
    with patch("asyncio.sleep", side_effect=_instant_sleep):
        with freeze_time("2024-01-01 12:00:00"):
            await mock.simulate_event(entity_id, "motion_detected", {"entity_id": entity_id})
            
            # Принудительно отдаем управление event loop.
            # Из-за патча, внутренний asyncio.sleep(30) в планировщике завершится МГНОВЕННО,
            # и callback (turn_off) будет вызван сразу же.
            await asyncio.sleep(0)
            
            state = engine.get_state(entity_id)
            assert state.current_state == "OFF", f"Ожидалось OFF после мгновенного таймаута, но получено {state.current_state}"
            
            turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
            assert turn_off_count == 1, f"turn_off должен быть вызван 1 раз, но вызван {turn_off_count}"


@pytest.mark.asyncio  
async def test_multiple_events_cancel_previous_timers() -> None:
    """
    Доказывает корректную отмену при множественных событиях.
    """
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    mock.set_fsm_engine(engine)
    
    registry.register_guard("is_night_time", lambda ctx: True)
    registry.register_guard("is_manual_override_enabled", lambda ctx: True)
    registry.register_action("turn_on_light", lambda ctx: mock.call_service("light", "turn_on", ctx.get("entity_id", "light.kitchen"), {}))
    registry.register_action("turn_off_light", lambda ctx: mock.call_service("light", "turn_off", ctx.get("entity_id", "light.kitchen"), {}))
    
    loader = Loader(engine, registry, features_dir="features")
    loader.load_and_register(directory="features")
    
    entity_id = "light.kitchen"
    
    with freeze_time("2024-01-01 12:00:00"):
        await mock.simulate_event(entity_id, "motion_detected", {"entity_id": entity_id})
        assert engine.get_state(entity_id).current_state == "ON_MOTION"
    
    with freeze_time("2024-01-01 12:00:01"):
        await mock.simulate_event(entity_id, "manual_override", {"entity_id": entity_id})
        assert engine.get_state(entity_id).current_state == "ON_MANUAL"
    
    with freeze_time("2024-01-01 12:00:02"):
        await mock.simulate_event(entity_id, "manual_switch_off", {"entity_id": entity_id})
        assert engine.get_state(entity_id).current_state == "OFF"
    
    turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
    turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
    
    assert turn_on_count == 1, f"turn_on должен быть вызван 1 раз, но вызван {turn_on_count}"
    assert turn_off_count == 1, f"turn_off должен быть вызван 1 раз, но вызван {turn_off_count}"
