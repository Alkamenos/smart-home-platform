#!/usr/bin/env python3
"""Full House Demo - Complete Smart Home Platform demonstration.

This script demonstrates the full integration of HAAdapter with EventRouter,
showing how sensor events are automatically routed to the appropriate FSMs
based on manifest configuration.

Features demonstrated:
- Loading manifest from YAML
- Creating FSMFactory and registering all behaviors
- Creating EventRouter for automatic event routing
- Creating HAAdapter with EventRouter integration
- Emulating sensor events (motion, temperature, manual switch)
- Logging FSM state transitions

Usage:
    python examples/full_house_demo.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from adapters.ha_adapter import HAAdapter

# Import core components
from core import FSMEngine, Manifest, Registry, load_manifest
from core.event_router import EventRouter
from core.fsm_factory import FSMFactory


class MockHass:
    """Mock Home Assistant instance for standalone testing."""

    def __init__(self) -> None:
        self.services = MockServices()


class MockServices:
    """Mock HA services for testing."""

    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> None:
        """Mock service call."""
        logger.info(f"📞 MOCK HA SERVICE: {domain}.{service} called with data={service_data}")


class MockEventBus:
    """Simple mock EventBus for testing."""

    def __init__(self) -> None:
        self._subscribers: list[tuple[str, Any]] = []

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> None:
        """Publish event to all subscribers."""
        log = logger.bind(trace_id=trace_id or "unknown")
        log.debug(f"EventBus: publishing {event_type} with payload={payload}")


async def setup_full_house_demo() -> tuple[FSMEngine, HAAdapter, EventRouter, Manifest]:
    """Set up the full house demo with all components.

    Returns:
        Tuple of (engine, adapter, router, manifest).
    """
    log = logger.bind(component="setup")

    print("=" * 70)
    print("🏠 Smart Home Platform - Full House Demo")
    print("=" * 70)

    # Step 1: Load manifest
    print("\n📄 Шаг 1: Загрузка манифеста...")
    manifest = load_manifest("instances/leonids_house/manifest.yaml")
    print(f"   ✅ Загружен манифест для '{manifest.instance.name}'")
    print(f"   📊 Устройств: {len(manifest.devices)}")

    # Step 2: Create core components
    print("\n⚙️  Шаг 2: Создание базовых компонентов...")
    engine = FSMEngine()
    registry = Registry()
    event_bus = MockEventBus()

    # Register standard guards and actions from features
    from smart_home.features.lighting import (
        turn_off_light,
        turn_off_night_light,
        turn_on_light,
        turn_on_night_light,
    )

    registry.register_guard("is_night_time", lambda state, ctx: False)  # Simple mock
    registry.register_action("turn_on_light", turn_on_light)
    registry.register_action("turn_off_light", turn_off_light)
    registry.register_action("turn_on_night_light", turn_on_night_light)
    registry.register_action("turn_off_night_light", turn_off_night_light)

    log.info("Core components created: FSMEngine, Registry, EventBus")

    # Step 3: Create FSMFactory and register all behaviors
    print("\n🏗️  Шаг 3: Создание FSM из манифеста...")
    factory = FSMFactory(engine=engine, registry=registry, event_bus=event_bus)
    definitions = factory.create_and_register(manifest)
    print(f"   ✅ Создано и зарегистрировано {len(definitions)} FSM определений")

    # Print registered FSMs
    for fsm_id in engine._definitions:
        state = engine.get_state(fsm_id)
        print(f"      • {fsm_id}: initial_state={state.current_state}")

    # Step 4: Create EventRouter
    print("\n🔀 Шаг 4: Создание EventRouter для маршрутизации событий...")
    router = EventRouter(manifest, engine)
    print("   ✅ EventRouter создан и настроен")

    # Show sensor mappings
    print("\n   📋 Маршруты сенсоров:")
    for sensor_id in router._sensor_to_fsms:
        mappings = router.get_mapping_for_sensor(sensor_id)
        for fsm_id, event_name in mappings:
            print(f"      • {sensor_id} -> {fsm_id} ({event_name})")

    # Step 5: Create HAAdapter with EventRouter
    print("\n🔌 Шаг 5: Создание HAAdapter с EventRouter...")
    mock_hass = MockHass()
    adapter = HAAdapter(
        mode="pyscript",
        engine=engine,
        hass=mock_hass,
        event_router=router,
    )
    print("   ✅ HAAdapter создан и связан с EventRouter")

    return engine, adapter, router, manifest


async def emulate_sensor_events(adapter: HAAdapter, engine: FSMEngine) -> None:
    """Emulate sensor events from Home Assistant.

    Args:
        adapter: HAAdapter instance.
        engine: FSMEngine instance.
    """
    logger.bind(component="demo")

    print("\n" + "=" * 70)
    print("🎬 Эмуляция событий от датчиков")
    print("=" * 70)

    # =========================================================================
    # СЦЕНАРИЙ 1: Датчик движения на кухне
    # =========================================================================
    print("\n📍 Сценарий 1: Датчик движения binary_sensor.kitchen_motion")
    print("-" * 70)

    print("   🔴 Движение обнаружено (off -> on)...")
    await adapter.on_state_change(
        entity_id="binary_sensor.kitchen_motion",
        new_state="on",
        old_state="off",
        context={"trace_id": "demo-motion-001"},
    )
    await asyncio.sleep(0.5)

    # Show FSM states after motion
    print("\n   📊 Состояния FSM после события движения:")
    for fsm_id in engine._definitions:
        if "kitchen" in fsm_id:
            state = engine.get_state(fsm_id)
            print(f"      • {fsm_id}: {state.current_state}")

    # =========================================================================
    # СЦЕНАРИЙ 2: Датчик температуры на кухне
    # =========================================================================
    print("\n📍 Сценарий 2: Датчик температуры sensor.kitchen_temperature")
    print("-" * 70)

    print("   🌡️  Температура изменилась (21.5 -> 22.5)...")
    await adapter.on_state_change(
        entity_id="sensor.kitchen_temperature",
        new_state="22.5",
        old_state="21.5",
        context={"trace_id": "demo-temp-001"},
    )
    await asyncio.sleep(0.5)

    # Show FSM states after temperature change
    print("\n   📊 Состояния FSM после изменения температуры:")
    for fsm_id in engine._definitions:
        if "climate.kitchen" in fsm_id:
            state = engine.get_state(fsm_id)
            print(f"      • {fsm_id}: {state.current_state}")

    # =========================================================================
    # СЦЕНАРИЙ 3: Ручное включение света на кухне
    # =========================================================================
    print("\n📍 Сценарий 3: Ручное включение light.kitchen")
    print("-" * 70)

    print("   ✋ Пользователь вручную включил свет (off -> on)...")
    await adapter.on_state_change(
        entity_id="light.kitchen",
        new_state="on",
        old_state="off",
        context={"trace_id": "demo-manual-001", "user_id": "user_123"},
    )
    await asyncio.sleep(0.5)

    # Show FSM states after manual override
    print("\n   📊 Состояния FSM после ручного включения:")
    for fsm_id in engine._definitions:
        if "light.kitchen" in fsm_id:
            state = engine.get_state(fsm_id)
            print(f"      • {fsm_id}: {state.current_state}")
            if state.context:
                print(f"         Context: {state.context}")

    # =========================================================================
    # СЦЕНАРИЙ 4: Датчик движения в гостиной
    # =========================================================================
    print("\n📍 Сценарий 4: Датчик движения binary_sensor.living_room_motion")
    print("-" * 70)

    print("   🔴 Движение обнаружено (off -> on)...")
    await adapter.on_state_change(
        entity_id="binary_sensor.living_room_motion",
        new_state="on",
        old_state="off",
        context={"trace_id": "demo-motion-002"},
    )
    await asyncio.sleep(0.5)

    # Show FSM states after living room motion
    print("\n   📊 Состояния FSM после события движения в гостиной:")
    for fsm_id in engine._definitions:
        if "living_room" in fsm_id:
            state = engine.get_state(fsm_id)
            print(f"      • {fsm_id}: {state.current_state}")

    # =========================================================================
    # ИТОГИ
    # =========================================================================
    print("\n" + "=" * 70)
    print("📊 ИТОГОВОЕ СОСТОЯНИЕ ВСЕХ FSM")
    print("=" * 70)

    for fsm_id in sorted(engine._definitions.keys()):
        state = engine.get_state(fsm_id)
        print(f"\n{fsm_id}:")
        print(f"   State: {state.current_state}")
        print(f"   Context: {state.context if state.context else '{}'}")

    print("\n" + "=" * 70)
    print("✅ Демо успешно завершено!")
    print("=" * 70)


async def main() -> None:
    """Main entry point for the demo."""
    # Configure logging
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
        level="INFO",
    )

    try:
        # Set up all components
        engine, adapter, router, manifest = await setup_full_house_demo()

        # Run sensor event emulation
        await emulate_sensor_events(adapter, engine)

        # Graceful shutdown
        print("\n🛑 Остановка демо...")
        await engine.shutdown()
        print("✅ Демо успешно завершено!")

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
