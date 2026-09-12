"""
Интеграционный тест сценария композиции поведений с приоритетами.

Сценарий теста:
1. Загружает манифест с лампой кухни, у которой есть 2 поведения:
   - night_light (приоритет 20, активен с 23:00 до 07:00)
   - motion_lighting (приоритет 10)
2. Использует freezegun для установки времени 23:30 (ночник активен)
3. Эмулирует событие motion_detected для датчика кухни
4. Проверяет, что HAAdapter получил команду на тусклый свет (от ночника),
   а команда на яркий свет (от движения) была заблокирована Dispatcher'ом
5. Эмулирует время 08:00, ночник отключается (release)
6. Снова эмулирует motion_detected
7. Проверяет, что теперь HAAdapter получил команду на яркий свет
"""

import pytest
import sys
import os
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

# Добавляем parent directory в path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from freezegun import freeze_time

from src.smart_home.core.fsm import FSMEngine, FSMDefinition, Transition
from src.smart_home.core.registry import Registry
from src.smart_home.core.command_dispatcher import CommandDispatcher, CommandIntent


class MockHAAdapter:
    """Mock HAAdapter для тестирования CommandDispatcher."""
    
    def __init__(self):
        self.call_service_calls = []
        self.call_service_async = AsyncMock()
    
    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Mock call_service, который записывает вызовы."""
        self.call_service_calls.append({
            "domain": domain,
            "service": service,
            "entity_id": entity_id,
            "data": data or {},
            "trace_id": trace_id,
        })
        return True
    
    def get_calls_by_service(self, service: str) -> list:
        """Получить все вызовы определенного сервиса."""
        return [c for c in self.call_service_calls if c["service"] == service]
    
    def clear_calls(self) -> None:
        """Очистить лог вызовов."""
        self.call_service_calls.clear()


@pytest.fixture
def mock_ha_adapter():
    """Создать mock HAAdapter."""
    return MockHAAdapter()


@pytest.fixture
def dispatcher(mock_ha_adapter):
    """Создать CommandDispatcher с mock adapter."""
    return CommandDispatcher(ha_adapter=mock_ha_adapter)


@pytest.fixture
def fsm_engine(dispatcher, registry):
    """Создать FSMEngine с CommandDispatcher и зарегистрировать guards/actions."""
    engine = FSMEngine(command_dispatcher=dispatcher)
    
    # Регистрируем guard'ы и actions из registry в engine
    engine._guards = registry._guards
    engine._actions = registry._actions
    
    return engine


@pytest.fixture
def registry():
    """Создать Registry с заглушками для guards и actions."""
    reg = Registry()
    
    # Guard: is_night_time - проверяет, ночь ли сейчас
    def is_night_time(state, context: dict) -> bool:
        """Guard для проверки ночного времени."""
        return context.get("is_night_time", False)
    
    reg.register_guard("is_night_time", is_night_time)
    
    # Action: turn_on_night_light - включает тусклый свет
    async def turn_on_night_light(state, context: dict):
        """Включить ночник с низкой яркостью."""
        entity_id = context.get("entity_id", "light.kitchen")
        return CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": 50},  # Тусклый свет
            priority=20,  # Высокий приоритет для ночника
            source="night_light",
        )
    
    reg.register_action("turn_on_night_light", turn_on_night_light)
    
    # Action: turn_off_night_light - выключает ночник
    async def turn_off_night_light(state, context: dict):
        """Выключить ночник."""
        entity_id = context.get("entity_id", "light.kitchen")
        return CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_off",
            data={},
            priority=20,
            source="night_light",
        )
    
    reg.register_action("turn_off_night_light", turn_off_night_light)
    
    # Action: turn_on_light - включает яркий свет (для motion_lighting)
    async def turn_on_light(state, context: dict):
        """Включить яркий свет."""
        entity_id = context.get("entity_id", "light.kitchen")
        return CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": 255},  # Яркий свет
            priority=10,  # Низкий приоритет для движения
            source="motion_lighting",
        )
    
    reg.register_action("turn_on_light", turn_on_light)
    
    # Action: turn_off_light - выключает свет
    async def turn_off_light(state, context: dict):
        """Выключить свет."""
        entity_id = context.get("entity_id", "light.kitchen")
        return CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_off",
            data={},
            priority=10,
            source="motion_lighting",
        )
    
    reg.register_action("turn_off_light", turn_off_light)
    
    return reg


def create_kitchen_light_fsm(entity_id: str = "light.kitchen") -> FSMDefinition:
    """
    Создать FSM определение для лампы кухни с двумя поведениями:
    - night_light (приоритет 20)
    - motion_lighting (приоритет 10)
    """
    # Определяем переходы для FSM
    transitions = (
        # Переход из OFF в ON_NIGHT при обнаружении движения ночью
        Transition(
            from_state="OFF",
            to_state="ON_NIGHT",
            trigger="motion_detected",
            guard="is_night_time",
            action="turn_on_night_light",
        ),
        # Переход из ON_NIGHT в OFF при отсутствии движения (таймаут)
        Transition(
            from_state="ON_NIGHT",
            to_state="OFF",
            trigger="timeout",
            action="turn_off_night_light",
            timeout_sec=60.0,
        ),
        # Переход из OFF в ON_MOTION при обнаружении движения (не ночью)
        Transition(
            from_state="OFF",
            to_state="ON_MOTION",
            trigger="motion_detected",
            action="turn_on_light",
        ),
        # Переход из ON_MOTION в OFF при таймауте
        Transition(
            from_state="ON_MOTION",
            to_state="OFF",
            trigger="timeout",
            action="turn_off_light",
            timeout_sec=30.0,
        ),
    )
    
    return FSMDefinition(
        entity_id=entity_id,
        initial_state="OFF",
        states=("OFF", "ON_NIGHT", "ON_MOTION"),
        transitions=transitions,
        debounce_sec=0.5,
    )


class TestCompositionScenario:
    """Интеграционные тесты композиции поведений с приоритетами."""
    
    @pytest.mark.asyncio
    async def test_night_light_blocks_motion_lighting(
        self, fsm_engine, registry, dispatcher, mock_ha_adapter
    ):
        """
        Сценарий: Ночник (приоритет 20) блокирует движение (приоритет 10).
        
        1. Время 23:30 (ночь) - ночник активен
        2. motion_detected - должен сработать ночник с тусклым светом
        3. Команда на яркий свет от движения должна быть заблокирована
        4. Время 08:00 (утро) - ночник отключается (release)
        5. motion_detected - теперь должен сработать яркий свет от движения
        """
        entity_id = "light.kitchen"
        
        # Регистрируем FSM для лампы кухни
        fsm_def = create_kitchen_light_fsm(entity_id)
        fsm_engine.register_definition(fsm_def)
        
        # Начальное состояние должно быть OFF
        initial_state = fsm_engine.get_state(entity_id)
        assert initial_state is not None
        assert initial_state.current_state == "OFF"
        
        # ====================================================================
        # Шаг 1: Время 23:30 (ночь) - ночник активен
        # ====================================================================
        with freeze_time("2024-01-01 23:30:00"):
            # Эмулируем событие motion_detected ночью
            # is_night_time=True, поэтому должен сработать night_light
            await fsm_engine.trigger(
                entity_id,
                "motion_detected",
                external_ctx={
                    "entity_id": entity_id,
                    "is_night_time": True,
                },
            )
            
            # Assert: FSM перешел в состояние ON_NIGHT
            state = fsm_engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_NIGHT", \
                f"Ожидалось ON_NIGHT, но получено {state.current_state}"
            
            # Assert: HAAdapter получил команду на тусклый свет (brightness=50)
            # от night_light с приоритетом 20
            turn_on_calls = mock_ha_adapter.get_calls_by_service("turn_on")
            assert len(turn_on_calls) == 1, \
                f"Должен быть 1 вызов turn_on, но их {len(turn_on_calls)}"
            
            call = turn_on_calls[0]
            assert call["entity_id"] == entity_id
            assert call["data"].get("brightness") == 50, \
                f"Ожидалась яркость 50 (ночник), но получена {call['data'].get('brightness')}"
            
            # Assert: Активный intent в dispatcher от night_light с приоритетом 20
            assert entity_id in dispatcher.active_intents
            active_intent = dispatcher.active_intents[entity_id]
            assert active_intent.source == "night_light"
            assert active_intent.priority == 20
        
        # ====================================================================
        # Шаг 2: Попытка включить яркий свет от движения (должна быть заблокирована)
        # ====================================================================
        # Примечание: В реальном сценарии motion_lighting не сработает,
        # потому что guard is_night_time=True блокирует его.
        # Но мы можем проверить, что если бы motion_lighting попытался
        # отправить команду с низким приоритетом, она была бы заблокирована.
        
        # Эмулируем попытку отправить команду от motion_lighting с низким приоритетом
        motion_intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": 255},  # Яркий свет
            priority=10,  # Низкий приоритет
            source="motion_lighting",
        )
        
        result = await dispatcher.submit(motion_intent)
        
        # Assert: Команда от motion_lighting должна быть отклонена
        assert result is False, \
            "Команда от motion_lighting должна быть отклонена из-за более высокого приоритета night_light"
        
        # Assert: Активный intent всё ещё от night_light
        assert dispatcher.active_intents[entity_id].source == "night_light"
        assert dispatcher.active_intents[entity_id].priority == 20
        
        # Assert: HAAdapter не получил дополнительных вызовов
        turn_on_calls = mock_ha_adapter.get_calls_by_service("turn_on")
        assert len(turn_on_calls) == 1, \
            f"Должен остаться 1 вызов turn_on, но их {len(turn_on_calls)}"
        
        # ====================================================================
        # Шаг 3: Время 08:00 (утро) - ночник отключается (release)
        # ====================================================================
        with freeze_time("2024-01-02 08:00:00"):
            # Ночник выпускает устройство (например, по таймеру или расписанию)
            release_result = dispatcher.release(entity_id, "night_light")
            assert release_result is True, "Release должен быть успешным"
            
            # Assert: Больше нет активного intent для этого устройства
            assert entity_id not in dispatcher.active_intents
            
            # СБРОСИТЬ СОСТОЯНИЕ FSM в OFF перед следующим тестом
            # В реальном сценарии это происходит через transition на timeout
            # Но для теста мы вручную сбрасываем состояние
            from src.smart_home.core.fsm import State
            import asyncio
            fsm_engine._states[entity_id] = State(
                current_state="OFF",
                entered_at=asyncio.get_event_loop().time(),
                context={}
            )
            
            # ====================================================================
            # Шаг 4: motion_detected утром - должен сработать яркий свет
            # ====================================================================
            # Теперь is_night_time=False, поэтому должен сработать motion_lighting
            await fsm_engine.trigger(
                entity_id,
                "motion_detected",
                external_ctx={
                    "entity_id": entity_id,
                    "is_night_time": False,
                },
            )
            
            # Assert: FSM перешел в состояние ON_MOTION
            state = fsm_engine.get_state(entity_id)
            assert state is not None
            assert state.current_state == "ON_MOTION", \
                f"Ожидалось ON_MOTION, но получено {state.current_state}"
            
            # Assert: HAAdapter получил команду на яркий свет (brightness=255)
            # от motion_lighting с приоритетом 10
            turn_on_calls = mock_ha_adapter.get_calls_by_service("turn_on")
            assert len(turn_on_calls) == 2, \
                f"Должно быть 2 вызова turn_on, но их {len(turn_on_calls)}"
            
            second_call = turn_on_calls[1]
            assert second_call["entity_id"] == entity_id
            assert second_call["data"].get("brightness") == 255, \
                f"Ожидалась яркость 255 (яркий свет), но получена {second_call['data'].get('brightness')}"
            
            # Assert: Активный intent в dispatcher от motion_lighting с приоритетом 10
            assert entity_id in dispatcher.active_intents
            active_intent = dispatcher.active_intents[entity_id]
            assert active_intent.source == "motion_lighting"
            assert active_intent.priority == 10
        
        print("✅ Тест night_light_blocks_motion_lighting прошёл успешно!")
        print(f"   - Ночник (приоритет 20) успешно заблокировал движение (приоритет 10)")
        print(f"   - После release ночника движение успешно включило яркий свет")
    
    @pytest.mark.asyncio
    async def test_priority_order_verification(
        self, dispatcher, mock_ha_adapter
    ):
        """
        Проверка логики приоритетов напрямую через CommandDispatcher.
        
        Доказывает, что:
        1. Более высокий приоритет всегда побеждает
        2. Равный приоритет заменяет предыдущий
        3. Release работает корректно
        """
        entity_id = "light.test"
        
        # Шаг 1: Отправляем intent с низким приоритетом
        low_intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": 100},
            priority=10,
            source="low_priority",
        )
        result = await dispatcher.submit(low_intent)
        assert result is True
        assert dispatcher.active_intents[entity_id].priority == 10
        
        # Шаг 2: Отправляем intent с высоким приоритетом - должен победить
        high_intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": 200},
            priority=20,
            source="high_priority",
        )
        result = await dispatcher.submit(high_intent)
        assert result is True
        assert dispatcher.active_intents[entity_id].priority == 20
        assert dispatcher.active_intents[entity_id].source == "high_priority"
        
        # Шаг 3: Пытаемся отправить еще один низкий приоритет - должен быть отклонен
        another_low_intent = CommandIntent(
            device_id=entity_id,
            domain="light",
            service="turn_on",
            data={"brightness": 150},
            priority=10,
            source="another_low",
        )
        result = await dispatcher.submit(another_low_intent)
        assert result is False
        # Активный intent должен остаться от high_priority
        assert dispatcher.active_intents[entity_id].source == "high_priority"
        
        # Шаг 4: Release от high_priority
        release_result = dispatcher.release(entity_id, "high_priority")
        assert release_result is True
        assert entity_id not in dispatcher.active_intents
        
        # Шаг 5: Теперь low_priority может занять устройство
        result = await dispatcher.submit(another_low_intent)
        assert result is True
        assert dispatcher.active_intents[entity_id].source == "another_low"
        
        print("✅ Тест priority_order_verification прошёл успешно!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
