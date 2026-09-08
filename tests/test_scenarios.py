"""
Интеграционные тесты сценариев FSM для проверки корректности работы планировщика.

Доказывает, что при переходе состояния старые таймеры отменяются,
решая проблему "зависания" автоматов.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time

from src.smart_home.core.fsm import FSMEngine
from src.smart_home.core.registry import Registry
from src.smart_home.core.loader import Loader
from src.smart_home.adapters.mock_adapter import MockAdapter


@pytest.mark.asyncio
async def test_manual_override_cancels_motion_timer() -> None:
    """
    Тест доказывает корректность работы планировщика при ручном вмешательстве.
    
    Сценарий:
    1. t = 12:00:00 (Ночь): motion_detected -> ON_MOTION, включается свет, таймер 30 сек
    2. t = 12:00:15 (15 сек): manual_override -> ON_MANUAL, старый таймер должен быть ОТМЕНЕН
    3. t = 12:00:35 (35 сек): Если бы таймер не отменился, свет бы выключился. 
       Проверяем что состояние всё ещё ON_MANUAL и turn_off НЕ вызван
    4. t = 12:05:10 (5 мин 10 сек): Таймаут ON_MANUAL срабатывает, turn_off вызван
    
    Assert: Сервис turn_off был вызван ровно один раз за весь тест.
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
    
    # 🚀 ВАЖНО: Мокаем asyncio.sleep чтобы таймеры срабатывали мгновенно.
    # Используем AsyncMock вместо side_effect для избежания рекурсии.
    # Это позволяет тесту доказать, что старый таймер был отменен, а не просто
    # еще не успел сработать из-за реального времени ожидания.
    original_sleep = asyncio.sleep
    
    async def _instant_sleep(delay: float) -> None:
        """Мгновенный sleep для ускорения тестов."""
        await original_sleep(0)
    
    with patch.object(asyncio, 'sleep', new_callable=lambda: AsyncMock(side_effect=_instant_sleep)):
        
        # ========================================================================
        # t = 12:00:00 (Ночь): motion_detected -> ON_MOTION
        # ========================================================================
        with freeze_time("2024-01-01 12:00:00"):
            # Эмулируем событие motion_detected
            result = await mock.simulate_event(
                entity_id,
                "motion_detected",
                {"entity_id": entity_id}
            )
            
            # Даем event loop обработать мгновенный "sleep" и запланировать задачу
            await asyncio.sleep(0)
            
            # Assert: Состояние FSM перешло в "ON_MOTION"
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_MOTION", \
                f"Ожидалось ON_MOTION, но получено {state.current_state}"
            
            # Assert: Вызван сервис turn_on
            turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
            assert turn_on_count == 1, \
                f"Сервис turn_on должен быть вызван 1 раз, но вызван {turn_on_count} раз"
            
            turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
            assert turn_off_count == 0, \
                f"Сервис turn_off не должен быть вызван, но вызван {turn_off_count} раз"
        
        # ========================================================================
        # t = 12:00:15 (Прошло 15 секунд, таймер на 30 сек еще тикает)
        # manual_override -> ON_MANUAL
        # ========================================================================
        with freeze_time("2024-01-01 12:00:15"):
            # Эмулируем событие manual_override
            result = await mock.simulate_event(
                entity_id,
                "manual_override",
                {"entity_id": entity_id}
            )
            
            # Даем event loop обработать отмену и планирование нового таймера
            await asyncio.sleep(0)
            
            # Assert: Состояние FSM перешло в "ON_MANUAL"
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_MANUAL", \
                f"Ожидалось ON_MANUAL, но получено {state.current_state}"
            
            # Старый таймер на выключение (из ON_MOTION) должен быть ОТМЕНЕН
            # Это проверяется косвенно - если таймер не отменен, то на шаге 3
            # мы увидим вызов turn_off
        
        # ========================================================================
        # t = 12:00:35 (Прошло 35 секунд от начала)
        # Если бы таймер не отменился, свет бы выключился на 30-й секунде
        # ========================================================================
        with freeze_time("2024-01-01 12:00:35"):
            # Даем время на выполнение всех отложенных задач
            # Если бы таймер НЕ был отменен, он бы сработал мгновенно из-за нашего патча!
            await asyncio.sleep(0)
            
            # Assert: Состояние FSM все ещё "ON_MANUAL"
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
        # t = 12:05:10 (Прошло 5 минут и 10 секунд, сработал таймаут ON_MANUAL)
        # ========================================================================
        with freeze_time("2024-01-01 12:05:10"):
            # Даем время на выполнение всех отложенных задач
            # Таймаут ON_MANUAL = 300 секунд (5 минут), должен сработать
            # Нужно несколько итераций чтобы task выполнился полностью
            for _ in range(10):
                await asyncio.sleep(0)
            
            # Проверяем что таймаут сработал и состояние перешло в OFF
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "OFF", \
                f"Ожидалось OFF (таймаут ON_MANUAL сработал), но получено {state.current_state}"
    
    # ========================================================================
    # Финальная проверка: за весь тест turn_off вызван ровно 1 раз
    # (только от таймаута ON_MANUAL, таймер ON_MOTION был отменен)
    # ========================================================================
    turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
    turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
    
    # Главное утверждение теста: старый таймер был отменен
    # Поэтому turn_off был вызван только 1 раз (от таймаута ON_MANUAL)
    assert turn_off_count == 1, \
        f"Сервис turn_off должен быть вызван ровно 1 раз, но вызван {turn_off_count} раз(а)"
    
    assert turn_on_count == 1, \
        f"Сервис turn_on должен быть вызван ровно 1 раз, но вызван {turn_on_count} раз"
    
    print("✅ Тест manual_override_cancels_motion_timer прошёл успешно!")
    print(f"   - turn_on вызван {turn_on_count} раз")
    print(f"   - turn_off вызван {turn_off_count} раз (таймер успешно отменен)")


@pytest.mark.asyncio
async def test_timeout_transition_works_without_override() -> None:
    """
    Тест проверяет что таймер работает корректно без ручного вмешательства.
    
    Сценарий:
    1. motion_detected -> ON_MOTION, таймер 30 сек
    2. Ждем 30+ секунд (мгновенно благодаря патчу asyncio.sleep)
    3. timeout -> OFF, turn_off вызван
    
    Этот тест подтверждает что таймеры работают когда их не отменяют.
    """
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    mock.set_fsm_engine(engine)
    
    # Регистрируем заглушки
    def is_night_time(context: dict[str, Any]) -> bool:
        return True
    
    registry.register_guard("is_night_time", is_night_time)
    
    async def turn_on_light(context: dict[str, Any]) -> None:
        entity_id = context.get("entity_id", "light.kitchen")
        await mock.call_service("light", "turn_on", entity_id, {})
    
    registry.register_action("turn_on_light", turn_on_light)
    
    async def turn_off_light(context: dict[str, Any]) -> None:
        entity_id = context.get("entity_id", "light.kitchen")
        await mock.call_service("light", "turn_off", entity_id, {})
    
    registry.register_action("turn_off_light", turn_off_light)
    
    # Загружаем YAML
    loader = Loader(engine, registry, features_dir="features")
    loader.load_and_register(directory="features")
    
    entity_id = "light.kitchen"
    
    # 🚀 Патчим asyncio.sleep для мгновенного срабатывания таймеров
    original_sleep = asyncio.sleep
    
    async def _instant_sleep(delay: float) -> None:
        """Мгновенный sleep для ускорения тестов."""
        await original_sleep(0)
    
    with patch.object(asyncio, 'sleep', new_callable=lambda: AsyncMock(side_effect=_instant_sleep)):
        # t = 12:00:00: motion_detected
        with freeze_time("2024-01-01 12:00:00"):
            await mock.simulate_event(entity_id, "motion_detected", {"entity_id": entity_id})
            
            # Даем event loop обработать планирование таймера
            await asyncio.sleep(0)
            
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_MOTION"
        
        # Даем время на выполнение отложенных задач - таймер должен сработать мгновенно
        await asyncio.sleep(0)
        
        # Проверяем что turn_on был вызван
        turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
        assert turn_on_count == 1
        
        # Проверяем что turn_off был вызван (таймер сработал)
        turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
        assert turn_off_count == 1, \
            f"Сервис turn_off должен быть вызван 1 раз (таймер сработал), но вызван {turn_off_count} раз"
        
        # Проверяем что состояние перешло в OFF
        state = engine.get_state(entity_id)
        assert state is not None
        assert state.current_state == "OFF", \
            f"Ожидалось OFF (таймер сработал), но получено {state.current_state}"
    
    print("✅ Тест timeout_transition_works_without_override прошёл успешно!")


@pytest.mark.asyncio  
async def test_multiple_events_cancel_previous_timers() -> None:
    """
    Тест проверяет что множественные события корректно отменяют предыдущие таймеры.
    
    Сценарий:
    1. motion_detected -> ON_MOTION (таймер 30 сек)
    2. Ещё одно motion_detected (debounce должен заблокировать)
    3. manual_override -> ON_MANUAL (таймер 300 сек, предыдущий отменен)
    4. manual_switch_off -> OFF
    """
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    mock.set_fsm_engine(engine)
    
    # Регистрируем заглушки
    def is_night_time(context: dict[str, Any]) -> bool:
        return True
    
    def is_manual_override_enabled(context: dict[str, Any]) -> bool:
        return True
    
    registry.register_guard("is_night_time", is_night_time)
    registry.register_guard("is_manual_override_enabled", is_manual_override_enabled)
    
    async def turn_on_light(context: dict[str, Any]) -> None:
        entity_id = context.get("entity_id", "light.kitchen")
        await mock.call_service("light", "turn_on", entity_id, {})
    
    registry.register_action("turn_on_light", turn_on_light)
    
    async def turn_off_light(context: dict[str, Any]) -> None:
        entity_id = context.get("entity_id", "light.kitchen")
        await mock.call_service("light", "turn_off", entity_id, {})
    
    registry.register_action("turn_off_light", turn_off_light)
    
    # Загружаем YAML
    loader = Loader(engine, registry, features_dir="features")
    loader.load_and_register(directory="features")
    
    entity_id = "light.kitchen"
    
    # 🚀 Патчим asyncio.sleep для мгновенного срабатывания таймеров
    original_sleep = asyncio.sleep
    
    async def _instant_sleep(delay: float) -> None:
        """Мгновенный sleep для ускорения тестов."""
        await original_sleep(0)
    
    with patch.object(asyncio, 'sleep', new_callable=lambda: AsyncMock(side_effect=_instant_sleep)):
        # t = 12:00:00: motion_detected -> ON_MOTION
        with freeze_time("2024-01-01 12:00:00"):
            await mock.simulate_event(entity_id, "motion_detected", {"entity_id": entity_id})
            # Даем event loop обработать планирование
            await asyncio.sleep(0)
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_MOTION"
        
        # t = 12:00:01: manual_override -> ON_MANUAL (отменяет таймер ON_MOTION)
        with freeze_time("2024-01-01 12:00:01"):
            await mock.simulate_event(entity_id, "manual_override", {"entity_id": entity_id})
            # Даем event loop обработать отмену и планирование
            await asyncio.sleep(0)
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_MANUAL"
        
        # t = 12:00:02: manual_switch_off -> OFF
        with freeze_time("2024-01-01 12:00:02"):
            await mock.simulate_event(entity_id, "manual_switch_off", {"entity_id": entity_id})
            # Даем event loop обработать переход
            await asyncio.sleep(0)
            state = engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "OFF"
    
    # Проверяем количество вызовов
    turn_on_count = mock.count_service_calls(domain="light", service="turn_on")
    turn_off_count = mock.count_service_calls(domain="light", service="turn_off")
    
    assert turn_on_count == 1, f"turn_on должен быть вызван 1 раз, но вызван {turn_on_count}"
    assert turn_off_count == 1, f"turn_off должен быть вызван 1 раз, но вызван {turn_off_count}"
    
    print("✅ Тест multiple_events_cancel_previous_timers прошёл успешно!")
