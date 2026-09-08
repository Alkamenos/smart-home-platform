"""
Тест сбоя устройства: платформа не падает при недоступности устройств.

Сценарий:
1. Датчик движения перестаёт слать события (эмуляция)
2. Платформа продолжает работать
3. Датчик восстанавливается
4. Платформа снова реагирует на события
"""
import pytest
from core.fsm import FSMEngine
from adapters.asyncio_scheduler import AsyncioScheduler
from core.event_bus import EventBus
from core.logger import Logger
from features.lighting import create_lighting_automations


@pytest.fixture
def system():
    """Создаёт тестовую систему"""
    event_bus = EventBus()
    logger = Logger(component="test")
    
    fsm = FSMEngine(event_bus, logger, AsyncioScheduler())
    
    # Регистрируем автоматы освещения для спальни
    lighting_defs = create_lighting_automations(["bedroom"])
    for definition in lighting_defs:
        fsm.register(definition)
    
    return {
        "fsm": fsm,
        "event_bus": event_bus,
        "logger": logger,
    }


@pytest.mark.asyncio
async def test_device_failure_graceful(system):
    """
    Тест: сбой устройства не роняет платформу.
    
    Проверяет что:
    - Платформа работает при отсутствии событий от датчика
    - Можно управлять вручную
    - При восстановлении датчика автоматика работает
    """
    fsm = system["fsm"]
    entity_id = "light.bedroom"
    
    # Начальное состояние - OFF
    state = fsm.get_state(entity_id)
    assert state.current == "OFF"
    
    # ========================================================================
    # Шаг 1: Датчик движения "сломался" - не шлёт события
    # Эмулируем это просто отсутствием вызова trigger с motion_detected
    # Платформа должна оставаться в текущем состоянии
    # ========================================================================
    
    # Проверяем что состояние не изменилось само по себе
    state = fsm.get_state(entity_id)
    assert state.current == "OFF", "Без событий состояние не должно меняться"
    
    # ========================================================================
    # Шаг 2: Платформа продолжает работать - пробуем ручное управление
    # ========================================================================
    result = fsm.trigger(entity_id, "manual_change", {
        "source": "manual",
        "user_action": "turn_on"
    })
    
    assert result is True, "Ручное управление должно работать"
    state = fsm.get_state(entity_id)
    assert state.current == "MANUAL", f"Свет должен быть MANUAL, а не {state.current}"
    
    # ========================================================================
    # Шаг 3: Пробуем включить по расписанию (датчик всё ещё "сломан")
    # Сначала вернёмся в OFF через timeout
    import time
    result = fsm.trigger(entity_id, "timeout", {
        "source": "system",
        "bedroom_manual_entered_at": time.time() - (61 * 60)
    })
    assert result is True
    
    # Теперь включаем по расписанию
    result = fsm.trigger(entity_id, "schedule_on", {
        "bedroom_is_schedule_time": True,
        "bedroom_is_night_time": False,
        "source": "schedule"
    })
    
    assert result is True, "Расписание должно работать без датчика"
    state = fsm.get_state(entity_id)
    assert state.current == "ON_SCHEDULE", f"Свет должен быть ON_SCHEDULE, а не {state.current}"
    
    # ========================================================================
    # Шаг 4: Датчик "восстановился" - шлёт событие
    # ========================================================================
    result = fsm.trigger(entity_id, "motion_detected", {
        "bedroom_motion_sensor": True,
        "bedroom_motion_enabled": True,
        "source": "automation"
    })
    
    assert result is True, "После восстановления датчик должен работать"
    state = fsm.get_state(entity_id)
    assert state.current == "ON_MOTION", f"Свет должен быть ON_MOTION, а не {state.current}"
    
    print("✅ Тест сбоя устройства прошёл успешно!")


@pytest.mark.asyncio
async def test_platform_works_without_motion_sensor(system):
    """
    Тест: платформа работает когда датчик движения недоступен.
    
    Проверяет что другие триггеры (расписание, ручное) работают.
    """
    fsm = system["fsm"]
    entity_id = "light.bedroom"
    
    # Включаем по расписанию
    result = fsm.trigger(entity_id, "schedule_on", {
        "bedroom_is_schedule_time": True,
        "bedroom_is_night_time": False,
        "source": "schedule"
    })
    assert result is True
    assert fsm.get_state(entity_id).current == "ON_SCHEDULE"
    
    # Выключаем по расписанию
    result = fsm.trigger(entity_id, "schedule_off", {
        "bedroom_is_schedule_time": False,
        "source": "schedule"
    })
    assert result is True
    assert fsm.get_state(entity_id).current == "OFF"
    
    print("✅ Платформа работает без датчика движения")


@pytest.mark.asyncio
async def test_invalid_sensor_data_doesnt_crash(system):
    """
    Тест: некорректные данные от датчика не роняют платформу.
    
    Проверяет что платформа обрабатывает edge cases.
    """
    fsm = system["fsm"]
    entity_id = "light.bedroom"
    
    # Отправляем событие с некорректными данными
    result = fsm.trigger(entity_id, "motion_detected", {
        "bedroom_motion_sensor": None,  # None вместо bool
        "bedroom_motion_enabled": True,
        "source": "automation"
    })
    
    # Платформа не должна упасть, но переход может не состояться
    # Guard проверит значение и вернёт False
    assert result is False or fsm.get_state(entity_id).current != "ON_MOTION", \
        "Некорректные данные не должны включать свет"
    
    # Состояние должно остаться OFF
    state = fsm.get_state(entity_id)
    assert state.current == "OFF", "При некорректных данных состояние не должно меняться"
    
    print("✅ Некорректные данные обработаны gracefully")


@pytest.mark.asyncio
async def test_repeated_events_handled(system):
    """
    Тест: повторные события от датчика обрабатываются корректно.
    
    Проверяет что множественные срабатывания датчика не вызывают проблем.
    """
    fsm = system["fsm"]
    entity_id = "light.bedroom"
    
    # Множественные срабатывания датчика
    for i in range(5):
        result = fsm.trigger(entity_id, "motion_detected", {
            "bedroom_motion_sensor": True,
            "bedroom_motion_enabled": True,
            "source": "automation"
        })
        
        if i == 0:
            # Первое срабатывание включает свет
            assert result is True
            assert fsm.get_state(entity_id).current == "ON_MOTION"
        else:
            # Последующие могут не вызывать переход (уже в ON_MOTION)
            # Это нормально - FSM idempotent
            pass
    
    # Состояние должно быть ON_MOTION
    state = fsm.get_state(entity_id)
    assert state.current == "ON_MOTION", "После множественных срабатываний свет должен быть ON_MOTION"
    
    print("✅ Повторные события обработаны корректно")
