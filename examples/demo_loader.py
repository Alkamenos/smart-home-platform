"""
Пример использования Loader для загрузки YAML-конфигураций автоматов.

Этот скрипт демонстрирует, как загрузить YAML файлы из папки features/,
валидировать их через Pydantic и зарегистрировать в FSMEngine.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from src.smart_home.core.fsm import FSMEngine
from src.smart_home.core.registry import Registry
from src.smart_home.core.loader import Loader


# Пример guard функции - проверка ночного времени
def is_night_time(ctx: dict[str, Any]) -> bool:
    """Проверка, что сейчас ночное время (22:00 - 06:00)."""
    hour = ctx.get("hour", 12)
    return hour >= 22 or hour < 6


# Пример action функции - включение света
def turn_on_light(ctx: dict[str, Any]) -> None:
    """Включение света для указанной сущности."""
    entity_id = ctx.get("entity_id", "unknown")
    logger.info(f"🔦 Turning ON light for entity: {entity_id}")


# Пример action функции - выключение света
def turn_off_light(ctx: dict[str, Any]) -> None:
    """Выключение света для указанной сущности."""
    entity_id = ctx.get("entity_id", "unknown")
    logger.info(f"🌑 Turning OFF light for entity: {entity_id}")


# Пример guard функции - проверка ручного режима
def is_manual_override_enabled(ctx: dict[str, Any]) -> bool:
    """Проверка, включен ли ручной режим переопределения."""
    return ctx.get("manual_override_enabled", False)


async def main() -> None:
    """Основная функция демонстрации."""
    # Создание двигателя и реестра
    engine = FSMEngine()
    registry = Registry()

    # Регистрация guard/action функций в реестре
    registry.register_guard("is_night_time", is_night_time)
    registry.register_action("turn_on_light", turn_on_light)
    registry.register_action("turn_off_light", turn_off_light)
    registry.register_guard("is_manual_override_enabled", is_manual_override_enabled)

    # Создание загрузчика
    loader = Loader(engine, registry, features_dir="features")

    # Загрузка YAML файлов и регистрация в двигателе
    definitions = loader.load_and_register()

    print(f"\n✅ Loaded {len(definitions)} FSM definitions:")
    for d in definitions:
        print(f"  - {d.entity_id}: initial='{d.initial_state}', states={d.states}")

    # Демонстрация работы FSM
    print("\n🎬 Demo: Triggering events for 'light.kitchen'...")

    # Сценарий 1: Ночное время, обнаружение движения
    print("\n--- Scenario 1: Night time motion detection ---")
    await engine.trigger(
        "light.kitchen",
        "motion_detected",
        external_ctx={"hour": 23, "entity_id": "light.kitchen"}
    )
    state = engine.get_state("light.kitchen")
    print(f"Current state: {state.current_state if state else 'unknown'}")

    # Сценарий 2: Таймаут - возврат в OFF
    print("\n--- Scenario 2: Timeout transition ---")
    # Ждем 31 секунду для срабатывания таймаута
    await asyncio.sleep(31)
    state = engine.get_state("light.kitchen")
    print(f"Current state after timeout: {state.current_state if state else 'unknown'}")

    # Сценарий 3: Ручное включение
    print("\n--- Scenario 3: Manual switch on ---")
    await engine.trigger(
        "light.kitchen",
        "manual_switch_on",
        external_ctx={"entity_id": "light.kitchen"}
    )
    state = engine.get_state("light.kitchen")
    print(f"Current state: {state.current_state if state else 'unknown'}")

    # Корректное завершение работы
    await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
