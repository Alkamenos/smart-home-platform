#!/usr/bin/env python3
"""
Тест персистентности FSM Platform V3

Проверяет:
1. Сохранение состояния при переходе
2. Восстановление состояния при рестарте
3. Корректность истории переходов
"""

import sys
from pathlib import Path

# Добавляем parent директорию в path для импортов
sys.path.insert(0, str(Path(__file__).parent.parent))

# Импортируем из core напрямую (для запуска из platform_v3/tests/)
try:
    from core.fsm_persistence import FSMPersistence
    from adapters.asyncio_scheduler import AsyncioScheduler
    from core.event_bus import EventBus
    from core.logger import Logger
    from core.fsm import FSMEngine, FSMDefinition, Transition
except ImportError:
    from platform_v3.core.fsm_persistence import FSMPersistence
    from platform_v3.core.event_bus import EventBus
    from platform_v3.core.logger import Logger
    from platform_v3.core.fsm import FSMEngine, FSMDefinition


def test_persist_save_on_transition():
    """Тест 1: Сохранение состояния при переходе"""
    print("\n=== Тест 1: Сохранение при переходе ===")
    
    event_bus = EventBus()
    logger = Logger(component='test')
    fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
    
    class MockAdapter:
        async def set_entity_state(self, entity_id, service, data):
            return True
    
    adapter = MockAdapter()
    persistence = FSMPersistence(event_bus, fsm_engine, adapter, logger)
    persistence.enable_for_entity('light.test_room')
    
    # Регистрируем автомат с минимальными переходами для связности графа
    definition = FSMDefinition(
        entity_id='light.test_room',
        states=('OFF', 'ON', 'PARTY'),
        initial='OFF',
        transitions=(
            # Минимальные переходы чтобы граф был связный
            Transition(from_state='OFF', to_state='ON', trigger='turn_on'),
            Transition(from_state='ON', to_state='OFF', trigger='turn_off'),
            Transition(from_state='OFF', to_state='PARTY', trigger='party_on'),
            Transition(from_state='PARTY', to_state='OFF', trigger='party_off'),
        )
    )
    fsm_engine.register(definition)
    
    # Эмулируем переход
    event_bus.publish('fsm.transition', {
        'entity_id': 'light.test_room',
        'to_state': 'PARTY'
    })
    
    # Проверяем что состояние сохранено в кэш
    assert persistence._state_cache.get('light.test_room') == 'PARTY', \
        "Состояние не сохранено в кэш"
    
    # Проверяем что файл создан
    import json
    from pathlib import Path as PPath
    storage_file = PPath.home() / ".homeassistant" / ".storage" / "fsm_persistence" / "light_test_room_mode.json"
    assert storage_file.exists(), "Файл персистентности не создан"
    
    with open(storage_file, 'r') as f:
        data = json.load(f)
        assert data['state'] == 'PARTY', f"Неверное состояние в файле: {data['state']}"
    
    print("✓ Состояние сохранено в кэш и файл")
    return True


def test_persist_restore_on_start():
    """Тест 2: Восстановление состояния при старте"""
    print("\n=== Тест 2: Восстановление при старте ===")
    
    event_bus = EventBus()
    logger = Logger(component='test')
    fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
    
    class MockAdapter:
        async def set_entity_state(self, entity_id, service, data):
            return True
    
    adapter = MockAdapter()
    persistence = FSMPersistence(event_bus, fsm_engine, adapter, logger)
    persistence.enable_for_entity('light.test_room')
    
    # Регистрируем автомат (симуляция рестарта - начальное состояние OFF)
    definition = FSMDefinition(
        entity_id='light.test_room',
        states=('OFF', 'ON', 'PARTY'),
        initial='OFF',
        transitions=(Transition(from_state='OFF', to_state='ON', trigger='turn_on'), Transition(from_state='ON', to_state='OFF', trigger='turn_off'))
    )
    fsm_engine.register(definition)
    
    # Проверяем начальное состояние
    initial_state = fsm_engine.get_state('light.test_room')
    assert initial_state.current == 'OFF', f"Начальное состояние неверно: {initial_state.current}"
    
    # Эмулируем событие platform.started (восстановление)
    event_bus.publish('platform.started', {})
    
    # Проверяем что состояние восстановилось
    restored_state = fsm_engine.get_state('light.test_room')
    assert restored_state.current == 'PARTY', \
        f"Состояние не восстановилось: {restored_state.current}"
    
    # Проверяем что запись в истории добавлена
    assert len(restored_state.history) > 0, "История пуста после восстановления"
    assert restored_state.history[0]['from'] == 'OFF', "Неверный from в истории"
    assert restored_state.history[0]['to'] == 'PARTY', "Неверный to в истории"
    assert restored_state.history[0]['trigger'] == 'restore', "Неверный trigger в истории"
    
    print("✓ Состояние восстановлено с записью в истории")
    return True


def test_persist_multiple_entities():
    """Тест 3: Персистентность для нескольких автоматов"""
    print("\n=== Тест 3: Несколько автоматов ===")
    
    event_bus = EventBus()
    logger = Logger(component='test')
    fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
    
    class MockAdapter:
        async def set_entity_state(self, entity_id, service, data):
            return True
    
    adapter = MockAdapter()
    persistence = FSMPersistence(event_bus, fsm_engine, adapter, logger)
    
    # Включаем для нескольких комнат
    rooms = ['living_room', 'bedroom', 'kitchen']
    for room in rooms:
        persistence.enable_for_entity(f'light.{room}')
        
        definition = FSMDefinition(
            entity_id=f'light.{room}',
            states=('OFF', 'ON'),
            initial='OFF',
            transitions=(Transition(from_state='OFF', to_state='ON', trigger='turn_on'), Transition(from_state='ON', to_state='OFF', trigger='turn_off'))
        )
        fsm_engine.register(definition)
    
    # Сохраняем разные состояния
    event_bus.publish('fsm.transition', {'entity_id': 'light.living_room', 'to_state': 'ON'})
    event_bus.publish('fsm.transition', {'entity_id': 'light.bedroom', 'to_state': 'ON'})
    event_bus.publish('fsm.transition', {'entity_id': 'light.kitchen', 'to_state': 'ON'})
    
    # Проверяем кэш
    assert len(persistence._state_cache) == 3, "Не все состояния в кэше"
    assert all(state == 'ON' for state in persistence._state_cache.values()), "Не все состояния ON"
    
    print("✓ Все автоматы сохранены")
    return True


def test_persist_invalid_state():
    """Тест 4: Игнорирование невалидных состояний"""
    print("\n=== Тест 4: Невалидное состояние ===")
    
    event_bus = EventBus()
    logger = Logger(component='test')
    fsm_engine = FSMEngine(event_bus, logger, AsyncioScheduler())
    
    class MockAdapter:
        async def set_entity_state(self, entity_id, service, data):
            return True
    
    adapter = MockAdapter()
    persistence = FSMPersistence(event_bus, fsm_engine, adapter, logger)
    persistence.enable_for_entity('light.test_room')
    
    # Создаём файл с невалидным состоянием
    import json
    from pathlib import Path as PPath
    storage_dir = PPath.home() / ".homeassistant" / ".storage" / "fsm_persistence"
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    storage_file = storage_dir / "light_test_room_mode_fake.json"
    with open(storage_file, 'w') as f:
        json.dump({'state': 'INVALID_STATE_123', 'updated_at': 12345}, f)
    
    # Включаем персистентность с кастомным ключом
    persistence.enable_for_entity('light.test_room_fake', 'light_test_room_mode_fake')
    
    definition = FSMDefinition(
        entity_id='light.test_room_fake',
        states=('OFF', 'ON'),  # INVALID_STATE_123 нет в списке
        initial='OFF',
        transitions=(Transition(from_state='OFF', to_state='ON', trigger='turn_on'), Transition(from_state='ON', to_state='OFF', trigger='turn_off'))
    )
    fsm_engine.register(definition)
    
    # Пытаемся восстановить
    event_bus.publish('platform.started', {})
    
    # Состояние должно остаться начальным
    state = fsm_engine.get_state('light.test_room_fake')
    assert state.current == 'OFF', \
        f"Невалидное состояние восстановилось: {state.current}"
    
    # Убираем тестовый файл
    storage_file.unlink(missing_ok=True)
    
    print("✓ Невалидное состояние отклонено")
    return True


if __name__ == '__main__':
    print("=" * 60)
    print("ТЕСТЫ ПЕРСИСТЕНТНОСТИ FSM Platform V3")
    print("=" * 60)
    
    tests = [
        test_persist_save_on_transition,
        test_persist_restore_on_start,
        test_persist_multiple_entities,
        test_persist_invalid_state,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"РЕЗУЛЬТАТЫ: {passed} пройдено, {failed} провалено")
    print("=" * 60)
    
    sys.exit(0 if failed == 0 else 1)
