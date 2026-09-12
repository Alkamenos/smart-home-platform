#!/usr/bin/env python3
"""Kitchen Demo - Local mock simulator for Smart Home FSM.

This script demonstrates the Smart Home FSM platform running locally
without Home Assistant. It simulates a kitchen lighting automation
with motion detection, manual override, and timeout handling.

Features:
- Simulates motion sensor events
- Demonstrates automatic light control
- Shows manual override functionality
- Displays trace_id propagation in logs
- Validates timer cancellation on rapid triggers

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
from src.smart_home.core.event_bus import EventBus
from src.smart_home.core.fsm import FSMEngine, State, FSMDefinition, Transition
from src.smart_home.core.registry import Registry
from src.smart_home.core.scheduler import Scheduler


def setup_kitchen_automations(
    engine: FSMEngine, adapter: MockAdapter
) -> None:
    """Set up kitchen lighting automations.

    Configures FSM states, transitions, guards, and actions for
    kitchen motion-based lighting with manual override support.

    Args:
        engine: FSMEngine instance to configure.
        adapter: MockAdapter for service calls.
    """
    log = logger.bind(component="kitchen_demo")

    # Define kitchen light entity
    kitchen_light = "light.kitchen"
    kitchen_motion = "binary_sensor.kitchen_motion"

    # Register guard: Check if manual override is active
    def is_not_manual_override(state: State, context: dict) -> bool:
        """Guard: Проверяет, не активна ли ручная блокировка."""
        manual_until = state.context.get("manual_override_until", 0.0)
        now = datetime.now().timestamp()

        if now < manual_until:
            log.debug(f"🛡️ GUARD: Ручная блокировка активна, переход отклонен.")
            return False
        return True

    def turn_on_light(state: State, context: dict) -> dict:
        """Включает свет. Не меняет контекст."""
        log.info("💡 LIGHT_ON: Включаем свет на кухне")
        # Здесь был бы вызов adapter.call_service("light.turn_on", ...)
        return {}

    def turn_off_light(state: State, context: dict) -> dict:
        """Выключает свет."""
        log.info("⬛ LIGHT_OFF: Выключаем свет на кухне")
        return {}

    def set_manual_override(state: State, context: dict) -> dict:
        """Устанавливает ручное управление и возвращает время истечения блокировки."""
        now = datetime.now().timestamp()
        override_until = now + 3600  # 60 минут
        log.info(
            f"✋ MANUAL: Ручное управление. Блокировка до {datetime.fromtimestamp(override_until).strftime('%H:%M:%S')}")

        # Возвращаем патч, который FSM добавит в state.context
        return {"manual_override_until": override_until}

    # Register guards and actions directly on engine
    engine.register_guard("not_manual_override", is_not_manual_override)
    engine.register_action("turn_on_light", turn_on_light)
    engine.register_action("turn_off_light", turn_off_light)
    engine.register_action("set_manual_override", set_manual_override)

    # Create transitions
    transitions = [
        # Motion detected: off → on_auto (timeout 5 min)
        Transition(
            from_state="off",
            trigger="motion_detected",
            to_state="on_auto",
            action="turn_on_light",
            timeout_sec=300,  # 5 minutes
        ),
        # Timeout: on_auto → off
        Transition(
            from_state="on_auto",
            trigger="timeout",
            to_state="off",
            action="turn_off_light",
        ),
        # Motion while on_auto: reset timer
        Transition(
            from_state="on_auto",
            trigger="motion_detected",
            to_state="on_auto",
            action="turn_on_light",
            timeout_sec=300,
        ),
        # Manual override: on_auto → on_manual (timeout 60 min)
        Transition(
            from_state="on_auto",
            trigger="manual_override",
            to_state="on_manual",
            action="set_manual_override",
            timeout_sec=3600,  # 60 minutes
        ),
        # Manual override: off → on_manual
        Transition(
            from_state="off",
            trigger="manual_override",
            to_state="on_manual",
            action="set_manual_override",
            timeout_sec=3600,
        ),
        # Timeout from manual: on_manual → off
        Transition(
            from_state="on_manual",
            trigger="timeout",
            to_state="off",
            action="turn_off_light",
        ),
        # Light turned off manually from any state
        Transition(
            from_state="on_auto",
            trigger="turned_off",
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

    # Create FSM definition
    fsm_def = FSMDefinition(
        entity_id=kitchen_light,
        initial_state="off",
        states=("off", "on_auto", "on_manual"),
        transitions=tuple(transitions),
    )

    # Register FSM definition
    engine.register_definition(fsm_def)

    log.info("Kitchen automations configured")


async def run_demo() -> None:
    """Run the kitchen demo simulation."""
    log = logger.bind(component="demo")

    print("=" * 60)
    print("🏠 Smart Home FSM - Kitchen Demo")
    print("=" * 60)
    print()

    # Initialize components
    engine = FSMEngine()
    adapter = MockAdapter()

    # Connect adapter to engine
    adapter.set_fsm_engine(engine)

    # Set up automations
    setup_kitchen_automations(engine, adapter)

    kitchen_light = "light.kitchen"
    kitchen_motion = "binary_sensor.kitchen_motion"

    print("Scenario: Kitchen Lighting Automation")
    print("-" * 60)
    print()

    # Scenario 1: Motion detected - trigger on light.kitchen entity
    print("📍 Step 1: Motion detected in kitchen")
    await asyncio.sleep(0.5)
    await adapter.simulate_event(
        kitchen_light,
        "motion_detected",
        {"trace_id": "demo0001"},
    )
    await asyncio.sleep(1)
    print()

    # Check state
    state = engine.get_state(kitchen_light)
    print(f"💡 Light FSM state: {state.current_state if state else 'N/A'}")
    print()

    # Scenario 2: Rapid motion triggers (test timer cancellation)
    print("📍 Step 2: Rapid motion triggers (testing timer cancellation)")
    await asyncio.sleep(0.5)
    for i in range(3):
        print(f"  Trigger {i + 1}/3")
        await adapter.simulate_event(
            kitchen_light,
            "motion_detected",
            {"trace_id": f"demo000{i + 2}"},
        )
        await asyncio.sleep(0.3)
    await asyncio.sleep(1)
    print()

    # Scenario 3: Manual override
    print("📍 Step 3: User activates manual override")
    await asyncio.sleep(0.5)
    await adapter.simulate_event(
        kitchen_light,
        "manual_override",
        {"trace_id": "demo0005"},
    )
    await asyncio.sleep(1)
    print()

    # Show service calls
    print("=" * 60)
    print("📋 Service Calls Log:")
    print("-" * 60)
    calls = adapter.get_service_calls()
    for i, call in enumerate(calls, 1):
        print(f"{i}. {call['domain']}.{call['service']}({call['entity_id']})")
    print()

    # Cleanup
    print("🛑 Stopping demo...")
    await engine.shutdown()
    print("✅ Demo completed successfully!")
    print()


if __name__ == "__main__":
    asyncio.run(run_demo())
