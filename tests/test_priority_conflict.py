"""
Интеграционные тесты для проверки композиции поведений и разрешения конфликтов приоритетов.

Доказывает, что CommandDispatcher корректно разрешает конфликты между
несколькими behaviors одного устройства на основе приоритетов.

Сценарий:
- У устройства light.kitchen есть два поведения:
  1. lighting (priority=10) - обычное освещение по движению
  2. night_light (priority=20) - ночник с высоким приоритетом

- Когда активен night_light, команды от lighting блокируются
- После release от night_light, lighting снова может управлять устройством
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from freezegun import freeze_time

from src.smart_home.core.fsm import FSMEngine
from src.smart_home.core.registry import Registry
from src.smart_home.core.command_dispatcher import CommandDispatcher, CommandIntent
from src.smart_home.core.fsm_factory import FSMFactory
from src.smart_home.adapters.mock_adapter import MockAdapter
from src.smart_home.core.models.manifest import Manifest, load_manifest


# ============================================================================
# Вспомогательные функции
# ============================================================================

async def _instant_sleep(delay: float, result: Any = None) -> Any:
    """Мгновенно возвращает управление, имитируя истечение таймаута."""
    return result


def create_test_manifest() -> Manifest:
    """
    Создает тестовый манифест с устройством, имеющим два поведения.

    Returns:
        Manifest: Валидированный манифест с light.kitchen и двумя behaviors.
    """
    manifest_dict = {
        "version": 1,  # <-- version на верхнем уровне
        "instance": {
            "id": "test_house",
            "name": "Test House",
            "owner": "Test",
            "created_at": "2026-01-01"
        },
        "zones": [
            {"id": "kitchen", "name": "Kitchen", "floor": 1}
        ],
        "automation_rules": {
            "lighting": {
                "motion_enabled": True,
                "schedule_enabled": True,
                "manual_lockout_min": 60
            },
            "climate": {  # <-- Добавляем climate
                "safety_lockout_enabled": True,
                "away_mode_enabled": True,
                "manual_lockout_min": 30
            },
            "ventilation": {  # <-- Добавляем ventilation
                "humidity_based": True,
                "manual_lockout_min": 15
            }
        },
        "dashboard": {  # <-- Добавляем dashboard
            "title": "Test Dashboard",
            "show_history": True,
            "show_climate": True,
            "show_motion_sensors": True,
            "history_days": 7
        },
        "devices": [
            {
                "type": "light_motion",
                "id": "light.kitchen",
                "name": "Kitchen Light",
                "room": "kitchen",
                "behaviors": [
                    {
                        "template": "lighting",
                        "priority": 10,
                        "params": {
                            "motion_sensor": "binary_sensor.kitchen_motion",
                            "motion_timeout_sec": 300,
                            "brightness": 255
                        }
                    },
                    {
                        "template": "night_light",
                        "priority": 20,
                        "params": {
                            "brightness": 10,
                            "schedule": "23:00-07:00"
                        }
                    }
                ]
            }
        ]
    }

    return Manifest.model_validate(manifest_dict)
@pytest.mark.asyncio
async def test_night_light_blocks_regular_lighting() -> None:
    """
    Тест 1: Ночник (priority=20) блокирует обычное освещение (priority=10).

    Сценарий:
    1. t=23:00 - Активируется night_light (priority=20)
    2. t=23:01 - Срабатывает датчик движения, lighting пытается включить свет (priority=10)
    3. Assert: Команда от lighting заблокирована, свет остается тусклым

    Доказывает, что CommandDispatcher корректно применяет приоритеты.
    """
    # ========================================================================
    # Инициализация
    # ========================================================================
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    dispatcher = CommandDispatcher(ha_adapter=mock)

    # Регистрируем guards и actions
    def is_day_time(context: dict[str, Any]) -> bool:
        """Всегда False (ночь)"""
        return False

    def is_night_time(context: dict[str, Any]) -> bool:
        """Всегда True (ночь)"""
        return True

    registry.register_guard("is_day_time", is_day_time)
    registry.register_guard("is_night_time", is_night_time)
    registry.register_guard("is_manual_override_enabled", lambda ctx: True)

    # Регистрируем action handlers, которые создают CommandIntent
    async def turn_on_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": context.get("brightness", 255)},
            priority=context.get("priority", 10),
            source=context.get("source", "lighting")
        )

        # Отправляем в dispatcher
        await dispatcher.submit(intent)
        return intent

    async def turn_off_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_off",
            data={},
            priority=context.get("priority", 10),
            source=context.get("source", "lighting")
        )

        await dispatcher.submit(intent)
        return intent

    async def turn_on_night_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": context.get("brightness", 10)},
            priority=context.get("priority", 20),
            source=context.get("source", "night_light")
        )

        await dispatcher.submit(intent)
        return intent

    async def turn_off_night_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_off",
            data={},
            priority=context.get("priority", 20),
            source=context.get("source", "night_light")
        )

        await dispatcher.submit(intent)
        return intent

    registry.register_action("turn_on_light", turn_on_light)
    registry.register_action("turn_off_light", turn_off_light)
    registry.register_action("turn_on_night_light", turn_on_night_light)
    registry.register_action("turn_off_night_light", turn_off_night_light)

    # Загружаем FSM через фабрику
    factory = FSMFactory(engine, registry, features_dir="features")
    manifest = create_test_manifest()
    definitions = factory.create_from_manifest(manifest)

    # Регистрируем все FSM в engine
    for fsm_def in definitions:
        engine.register_definition(fsm_def)

    # Проверяем, что созданы 2 FSM для light.kitchen
    assert len(definitions) == 2, f"Ожидалось 2 FSM, создано {len(definitions)}"

    # ========================================================================
    # t=23:00 - Активируется night_light (priority=20)
    # ========================================================================
    with freeze_time("2024-01-01 23:00:00"):
        # Эмулируем событие для night_light
        # FSM для night_light имеет entity_id вида "light.kitchen__night_light_20" (с двумя подчеркиваниями)
        night_light_fsm_id = "light.kitchen__night_light_20"

        # Триггерим transition в night_light FSM
        await engine.trigger(night_light_fsm_id, "motion_detected", {"entity_id": "light.kitchen"})

        # Даем время на выполнение action
        await asyncio.sleep(0)

        # Assert: night_light отправил команду
        assert "light.kitchen" in dispatcher.active_intents, \
            "night_light должен захватить контроль над устройством"

        active_intent = dispatcher.active_intents["light.kitchen"]
        assert active_intent.source == "night_light", \
            f"Ожидался source=night_light, но получен {active_intent.source}"
        assert active_intent.priority == 20, \
            f"Ожидался priority=20, но получен {active_intent.priority}"
        assert active_intent.data.get("brightness") == 10, \
            f"Ожидалась яркость 10, но получена {active_intent.data.get('brightness')}"

        # Assert: MockAdapter получил команду turn_on с яркостью 10
        turn_on_calls = mock.get_service_calls(domain="light", service="turn_on")
        assert len(turn_on_calls) == 1, \
            f"Должен быть ровно 1 вызов turn_on, но найдено {len(turn_on_calls)}"
        assert turn_on_calls[0]["data"]["brightness"] == 10, \
            f"Яркость должна быть 10 (ночник), но получена {turn_on_calls[0]['data']['brightness']}"

    # ========================================================================
    # t=23:01 - Срабатывает датчик движения, lighting пытается включить свет (priority=10)
    # ========================================================================
    with freeze_time("2024-01-01 23:01:00"):
        # Эмулируем событие для lighting FSM
        lighting_fsm_id = "light.kitchen_lighting_10"

        # Триггерим transition в lighting FSM
        await engine.trigger(lighting_fsm_id, "motion_detected", {"entity_id": "light.kitchen"})

        # Даем время на выполнение action
        await asyncio.sleep(0)

        # Assert: lighting попытался отправить команду, но она заблокирована
        # Active intent должен остаться от night_light
        active_intent = dispatcher.active_intents["light.kitchen"]
        assert active_intent.source == "night_light", \
            f"night_light должен сохранять контроль, но активен {active_intent.source}"
        assert active_intent.priority == 20, \
            f"Приоритет должен остаться 20, но получен {active_intent.priority}"

        # Assert: MockAdapter НЕ получил новую команду turn_on с яркостью 255
        turn_on_calls = mock.get_service_calls(domain="light", service="turn_on")
        assert len(turn_on_calls) == 1, \
            f"Должен быть только 1 вызов turn_on (от night_light), но найдено {len(turn_on_calls)}"

        # Проверяем, что единственный вызов был с яркостью 10 (ночник), а не 255 (обычный свет)
        assert turn_on_calls[0]["data"]["brightness"] == 10, \
            f"Яркость должна остаться 10 (ночник), но получена {turn_on_calls[0]['data']['brightness']}"

    print("✅ Тест night_light_blocks_regular_lighting прошёл успешно!")
    print(f" - night_light (priority=20) успешно заблокировал lighting (priority=10)")
    print(f" - MockAdapter получил только 1 команду turn_on с яркостью 10")


@pytest.mark.asyncio
async def test_release_allows_lower_priority() -> None:
    """
    Тест 2: После release от night_light, lighting снова может управлять устройством.

    Сценарий:
    1. t=23:00 - Активируется night_light (priority=20)
    2. t=23:05 - night_light делает release (таймер истек)
    3. t=23:06 - Срабатывает датчик движения, lighting включает свет (priority=10)
    4. Assert: Команда от lighting успешно выполнена

    Доказывает, что release корректно освобождает устройство.
    """
    # ========================================================================
    # Инициализация (такая же, как в первом тесте)
    # ========================================================================
    engine = FSMEngine()
    registry = Registry()
    mock = MockAdapter()
    dispatcher = CommandDispatcher(ha_adapter=mock)

    registry.register_guard("is_day_time", lambda ctx: True)  # Теперь день
    registry.register_guard("is_night_time", lambda ctx: False)
    registry.register_guard("is_manual_override_enabled", lambda ctx: True)

    async def turn_on_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": context.get("brightness", 255)},
            priority=context.get("priority", 10),
            source=context.get("source", "lighting")
        )

        await dispatcher.submit(intent)
        return intent

    async def turn_off_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_off",
            data={},
            priority=context.get("priority", 10),
            source=context.get("source", "lighting")
        )

        await dispatcher.submit(intent)
        # После turn_off освобождаем устройство
        dispatcher.release(entity_id, context.get("source", "lighting"))
        return intent

    async def turn_on_night_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": context.get("brightness", 10)},
            priority=context.get("priority", 20),
            source=context.get("source", "night_light")
        )

        await dispatcher.submit(intent)
        return intent

    async def turn_off_night_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
        entity_id = context.get("entity_id") or context.get("device_id")
        if not entity_id:
            return None

        intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_off",
            data={},
            priority=context.get("priority", 20),
            source=context.get("source", "night_light")
        )

        await dispatcher.submit(intent)
        # После turn_off освобождаем устройство
        dispatcher.release(entity_id, context.get("source", "night_light"))
        return intent

    registry.register_action("turn_on_light", turn_on_light)
    registry.register_action("turn_off_light", turn_off_light)
    registry.register_action("turn_on_night_light", turn_on_night_light)
    registry.register_action("turn_off_night_light", turn_off_night_light)

    factory = FSMFactory(engine, registry, features_dir="features")
    manifest = create_test_manifest()
    definitions = factory.create_from_manifest(manifest)

    for fsm_def in definitions:
        engine.register_definition(fsm_def)

    # ========================================================================
    # t=23:00 - Активируется night_light (priority=20)
    # ========================================================================
    with freeze_time("2024-01-01 23:00:00"):
        night_light_fsm_id = "light.kitchen_night_light_20"
        await engine.trigger(night_light_fsm_id, "motion_detected", {"entity_id": "light.kitchen"})
        await asyncio.sleep(0)

        # Assert: night_light активен
        assert "light.kitchen" in dispatcher.active_intents
        assert dispatcher.active_intents["light.kitchen"].source == "night_light"

    # ========================================================================
    # t=23:05 - night_light делает release (таймер истек)
    # ========================================================================
    with freeze_time("2024-01-01 23:05:00"):
        # Эмулируем timeout в night_light FSM
        await engine.trigger(night_light_fsm_id, "timeout", {"entity_id": "light.kitchen"})
        await asyncio.sleep(0)

        # Assert: night_light освободил устройство
        assert "light.kitchen" not in dispatcher.active_intents, \
            "После release устройство должно быть свободно"

        # Assert: MockAdapter получил команду turn_off
        turn_off_calls = mock.get_service_calls(domain="light", service="turn_off")
        assert len(turn_off_calls) == 1, \
            f"Должен быть 1 вызов turn_off, но найдено {len(turn_off_calls)}"

    # ========================================================================
    # t=23:06 - Срабатывает датчик движения, lighting включает свет (priority=10)
    # ========================================================================
    with freeze_time("2024-01-01 23:06:00"):
        lighting_fsm_id = "light.kitchen_lighting_10"
        await engine.trigger(lighting_fsm_id, "motion_detected", {"entity_id": "light.kitchen"})
        await asyncio.sleep(0)

        # Assert: lighting успешно захватил устройство
        assert "light.kitchen" in dispatcher.active_intents, \
            "lighting должен захватить устройство после release"

        active_intent = dispatcher.active_intents["light.kitchen"]
        assert active_intent.source == "lighting", \
            f"Ожидался source=lighting, но получен {active_intent.source}"
        assert active_intent.priority == 10, \
            f"Ожидался priority=10, но получен {active_intent.priority}"

        # Assert: MockAdapter получил команду turn_on с яркостью 255
        turn_on_calls = mock.get_service_calls(domain="light", service="turn_on")
        assert len(turn_on_calls) == 2, \
            f"Должно быть 2 вызова turn_on (1 от night_light, 1 от lighting), но найдено {len(turn_on_calls)}"

        # Проверяем последний вызов (от lighting)
        last_call = turn_on_calls[-1]
        assert last_call["data"]["brightness"] == 255, \
            f"Яркость должна быть 255 (обычный свет), но получена {last_call['data']['brightness']}"

    print("✅ Тест release_allows_lower_priority прошёл успешно!")
    print(f" - night_light успешно освободил устройство через release()")
    print(f" - lighting успешно захватил устройство и включил свет на 100%")


@pytest.mark.asyncio
async def test_ownership_protection() -> None:
    """
    Тест 3: Защита от неправильного release (ownership protection).

    Сценарий:
    1. night_light захватывает устройство
    2. lighting пытается сделать release (не должен succeed)
    3. Assert: Устройство остается под контролем night_light

    Доказывает, что только владелец может освободить устройство.
    """
    # ========================================================================
    # Инициализация
    # ========================================================================
    mock = MockAdapter()
    dispatcher = CommandDispatcher(ha_adapter=mock)

    # night_light захватывает устройство
    night_intent = CommandIntent(
        device_id="light.kitchen",
        domain="light",
        service="turn_on",
        data={"brightness": 10},
        priority=20,
        source="night_light"
    )

    await dispatcher.submit(night_intent)

    # Assert: night_light активен
    assert "light.kitchen" in dispatcher.active_intents
    assert dispatcher.active_intents["light.kitchen"].source == "night_light"

    # ========================================================================
    # lighting пытается сделать release (не должен succeed)
    # ========================================================================
    result = dispatcher.release("light.kitchen", "lighting")

    # Assert: release отклонен
    assert result is False, "release от чужого source должен вернуть False"

    # Assert: Устройство остается под контролем night_light
    assert "light.kitchen" in dispatcher.active_intents, \
        "Устройство не должно быть освобождено чужим source"
    assert dispatcher.active_intents["light.kitchen"].source == "night_light", \
        "Источник контроля не должен измениться"

    # ========================================================================
    # night_light делает release (должен succeed)
    # ========================================================================
    result = dispatcher.release("light.kitchen", "night_light")

    # Assert: release успешен
    assert result is True, "release от правильного source должен вернуть True"
    assert "light.kitchen" not in dispatcher.active_intents, \
        "Устройство должно быть освобождено"

    print("✅ Тест ownership_protection прошёл успешно!")
    print(f" - lighting не смог освободить устройство, контролируемое night_light")
    print(f" - night_light успешно освободил своё устройство")


if __name__ == "__main__":
    # Для ручного запуска тестов
    asyncio.run(test_night_light_blocks_regular_lighting())
    asyncio.run(test_release_allows_lower_priority())
    asyncio.run(test_ownership_protection())
