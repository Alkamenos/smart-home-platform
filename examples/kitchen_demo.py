#!/usr/bin/env python3
"""Kitchen Demo - Local mock simulator for Smart Home FSM.

This script demonstrates the Smart Home FSM platform running locally
without Home Assistant.

Features demonstrated:
- Motion-based lighting with debounce protection
- Manual override with context persistence (blocking automation)
- Async timer cancellation on rapid triggers
- Real async timeout execution (shortened for demo visibility)
- Trace ID propagation in logs

Usage:
    make run-mock
    or
    python examples/kitchen_demo.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger

from src.smart_home.adapters.mock_adapter import MockAdapter
from src.smart_home.core.fsm import FSMEngine, State, FSMDefinition, Transition


def setup_kitchen_automations(engine: FSMEngine, adapter: MockAdapter) -> None:
    """Set up kitchen lighting automations."""
    log = logger.bind(component="kitchen_demo")

    kitchen_light = "light.kitchen"

    # --- Guards & Actions ---

    def is_not_manual_override(state: State, context: dict) -> bool:
        manual_until = state.context.get("manual_override_until", 0.0)
        now = datetime.now().timestamp()
        if now < manual_until:
            remaining = int(manual_until - now)
            log.debug(f"🛡️ GUARD: Ручная блокировка активна (осталось {remaining}с), переход отклонен.")
            return False
        return True

    def turn_on_light(state: State, context: dict) -> dict:
        log.info("💡 LIGHT_ON: Включаем свет на кухне")
        return {}

    def turn_off_light(state: State, context: dict) -> dict:
        log.info("⬛ LIGHT_OFF: Выключаем свет на кухне (таймер или вручную)")
        return {}

    def set_manual_override(state: State, context: dict) -> dict:
        now = datetime.now().timestamp()
        override_until = now + 10  # ДЕМО: 10 секунд вместо 3600 для наглядности
        log.info(
            f"✋ MANUAL: Ручное управление. Блокировка на 10с (до {datetime.fromtimestamp(override_until).strftime('%H:%M:%S')})")
        return {"manual_override_until": override_until}

    def increment_motion_count(state: State, context: dict) -> dict:
        current = state.context.get("motion_count", 0)
        new_count = current + 1
        log.info(f"📊 MOTION COUNT: Сработал датчик движения (всего: {new_count})")
        return {"motion_count": new_count}

    # Register
    engine.register_guard("not_manual_override", is_not_manual_override)
    engine.register_action("turn_on_light", turn_on_light)
    engine.register_action("turn_off_light", turn_off_light)
    engine.register_action("set_manual_override", set_manual_override)
    engine.register_action("increment_motion_count", increment_motion_count)

    # --- Transitions ---
    # ПРИМЕЧАНИЕ: Таймауты уменьшены (3с и 10с) только для демо, чтобы увидеть срабатывание async-таймера!
    transitions = [
        Transition(
            from_state="off",
            trigger="motion_detected",
            to_state="on_auto",
            guard="not_manual_override",  # Добавили guard!
            action="turn_on_light",
            timeout_sec=3.0,  # ДЕМО: 3 секунды
        ),
        Transition(
            from_state="on_auto",
            trigger="motion_detected",
            to_state="on_auto",
            guard="not_manual_override",
            action="increment_motion_count",
            timeout_sec=3.0,  # Сброс таймера при новом движении
        ),
        Transition(
            from_state="on_auto",
            trigger="timeout",
            to_state="off",
            action="turn_off_light",
        ),
        Transition(
            from_state="on_auto",
            trigger="manual_override",
            to_state="on_manual",
            action="set_manual_override",
            timeout_sec=10.0,  # ДЕМО: 10 секунд
        ),
        Transition(
            from_state="off",
            trigger="manual_override",
            to_state="on_manual",
            action="set_manual_override",
            timeout_sec=10.0,
        ),
        Transition(
            from_state="on_manual",
            trigger="timeout",
            to_state="off",
            action="turn_off_light",
        ),
        Transition(
            from_state="on_manual",
            trigger="turned_off",
            to_state="off",
            action="turn_off_light",
        ),
    ]

    fsm_def = FSMDefinition(
        entity_id=kitchen_light,
        initial_state="off",
        states=("off", "on_auto", "on_manual"),
        transitions=tuple(transitions),
        debounce_sec=2.0,  # Защита от дребезга: игнорируем события чаще 2 секунд
    )

    engine.register_definition(fsm_def)
    log.info("✅ Kitchen automations configured")


async def run_demo() -> None:
    """Run the kitchen demo simulation with realistic async pacing."""
    log = logger.bind(component="demo")

    print("=" * 70)
    print("🏠 Smart Home FSM - Kitchen Demo (Async & Context)")
    print("=" * 70)
    print(
        "⚠️  ПРИМЕЧАНИЕ: Таймауты в демо уменьшены (3с и 10с) для наглядности\n    асинхронных действий. В продакшене используйте 300с и 3600с.")
    print("-" * 70)

    engine = FSMEngine()
    adapter = MockAdapter()
    adapter.set_fsm_engine(engine)

    setup_kitchen_automations(engine, adapter)

    kitchen_light = "light.kitchen"

    # ========================================================================
    # СЦЕНАРИЙ 1: Движение и Debounce
    # ========================================================================
    print("\n📍 Шаг 1: Обнаружено движение на кухне")
    await adapter.simulate_event(kitchen_light, "motion_detected", {"trace_id": "demo-001"})

    print("\n📍 Шаг 2: Быстрое повторное движение (через 1 сек)")
    print("   (Ожидается: игнорирование из-за debounce_sec=2.0)")
    await asyncio.sleep(1.0)
    result = await adapter.simulate_event(kitchen_light, "motion_detected", {"trace_id": "demo-002"})
    if not result:
        print("   ✅ Событие успешно заблокировано debounce!")

    # ========================================================================
    # СЦЕНАРИЙ 2: Демонстрация асинхронного таймаута
    # ========================================================================
    print("\n📍 Шаг 3: Ожидаем срабатывания асинхронного таймаута (3 секунды)...")
    print("   (Скрипт не блокируется, FSM работает в фоне)")

    # Проверяем состояние до таймаута
    state = engine.get_state(kitchen_light)
    print(f"   ⏳ Текущее состояние: {state.current_state}, Таймеров активно: {len(engine._timers)}")

    await asyncio.sleep(3.5)  # Даем таймеру сработать

    state = engine.get_state(kitchen_light)
    print(f"   ✅ Состояние после таймаута: {state.current_state}")

    # ========================================================================
    # СЦЕНАРИЙ 3: Ручное вмешательство и блокировка
    # ========================================================================
    print("\n📍 Шаг 4: Пользователь включает свет вручную (manual_override)")
    await adapter.simulate_event(kitchen_light, "manual_override", {"trace_id": "demo-003"})

    print("\n📍 Шаг 5: Попытка срабатывания датчика движения во время блокировки")
    await asyncio.sleep(0.5)
    result = await adapter.simulate_event(kitchen_light, "motion_detected", {"trace_id": "demo-004"})
    if not result:
        print("   ✅ Переход заблокирован guard'ом 'not_manual_override'!")

    # ========================================================================
    # ИТОГИ
    # ========================================================================
    print("\n" + "=" * 70)
    print("📊 ИТОГОВОЕ СОСТОЯНИЕ:")
    print("-" * 70)

    final_state = engine.get_state(kitchen_light)
    print(f"Устройство:   {kitchen_light}")
    print(f"Состояние FSM: {final_state.current_state}")
    print(f"Контекст:      {final_state.context}")
    print(f"Активных таймеров: {len(engine._timers)}")

    print("\n📋 Вызванные сервисы (MockAdapter):")
    calls = adapter.get_service_calls()
    if calls:
        for i, call in enumerate(calls, 1):
            print(f"  {i}. {call['domain']}.{call['service']}({call['entity_id']})")
    else:
        print("  (Нет вызовов сервисов, только логирование)")

    print("\n🛑 Остановка демо...")
    await engine.shutdown()
    print("✅ Демо успешно завершено!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_demo())
