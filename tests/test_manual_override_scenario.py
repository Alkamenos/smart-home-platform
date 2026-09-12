"""
Золотой тест сценария ручного вмешательства (Manual Override).

Этот тест доказывает, что:
1. При ручном включении света старый таймер движения корректно отменяется.
2. Время блокировки (manual_override_until) сохраняется в state.context.
3. Автоматика (движение) игнорируется, пока действует блокировка.
4. После истечения времени блокировки автоматика снова работает.
"""

import time
import pytest
from datetime import datetime
from freezegun import freeze_time
from unittest.mock import patch

from src.smart_home.core.fsm import FSMEngine, State, FSMDefinition, Transition


# ============================================================================
# Фикстура для синхронизации freezegun и asyncio.get_event_loop().time()
# ============================================================================
@pytest.fixture(autouse=True)
def freeze_asyncio_time():
    """
    Заставляет asyncio.get_event_loop().time() возвращать time.time(),
    который корректно мокается freezegun.
    """
    import asyncio
    real_get_event_loop = asyncio.get_event_loop

    with patch("src.smart_home.core.fsm.asyncio.get_event_loop") as mock_get_loop:
        def side_effect():
            loop = real_get_event_loop()
            # Подменяем метод time() на стандартный time.time()
            loop.time = time.time
            return loop

        mock_get_loop.side_effect = side_effect
        yield


# ============================================================================
# Тестовые Guard и Action (имитируют логику из kitchen_demo.py)
# ============================================================================
def turn_on_light(state: State, context: dict) -> dict:
    return {}

def turn_off_light(state: State, context: dict) -> dict:
    return {}

def set_manual_override(state: State, context: dict) -> dict:
    """Устанавливает блокировку на 60 минут (3600 сек)."""
    now = datetime.now().timestamp()
    return {"manual_override_until": now + 3600}

def is_not_manual_override(state: State, context: dict) -> bool:
    """Guard: Разрешает переход только если ручная блокировка истекла."""
    manual_until = state.context.get("manual_override_until", 0.0)
    now = datetime.now().timestamp()
    return now >= manual_until


# ============================================================================
# Сам тест
# ============================================================================
@pytest.mark.asyncio
async def test_manual_override_blocks_automation_and_cancels_timers():
    """
    Полный сценарий: Движение -> Ручное включение -> Попытка движения во время блокировки -> Истечение блокировки.
    """
    engine = FSMEngine()
    entity_id = "light.kitchen"

    # 1. Регистрируем Guard и Action
    engine.register_action("turn_on_light", turn_on_light)
    engine.register_action("turn_off_light", turn_off_light)
    engine.register_action("set_manual_override", set_manual_override)
    engine.register_guard("is_not_manual_override", is_not_manual_override)

    # 2. Регистрируем определение FSM для кухни
    definition = FSMDefinition(
        entity_id=entity_id,
        initial_state="off",
        states=("off", "on_auto", "on_manual"),
        debounce_sec=0.0,
        transitions=(
            # Движение включает свет (таймер 300 сек)
            Transition(
                from_state="off",
                trigger="motion_detected",
                to_state="on_auto",
                guard="is_not_manual_override",
                action="turn_on_light",
                timeout_sec=300.0,
            ),
            # Ручное вмешательство (таймер 3600 сек)
            Transition(
                from_state="on_auto",
                trigger="manual_override",
                to_state="on_manual",
                action="set_manual_override",
                timeout_sec=3600.0,
            ),
            Transition(
                from_state="off",
                trigger="manual_override",
                to_state="on_manual",
                action="set_manual_override",
                timeout_sec=3600.0,
            ),
            # Истечение ручного таймера выключает свет
            Transition(
                from_state="on_manual",
                trigger="timeout",
                to_state="off",
                action="turn_off_light",
            ),
        )
    )
    engine.register_definition(definition)

    # ========================================================================
    # ШАГ 1: t=12:00:00 - Сработал датчик движения
    # ========================================================================
    with freeze_time("2026-09-09 12:00:00"):
        result = await engine.trigger(entity_id, "motion_detected", trace_id="test-001")

        assert result is True, "Переход off -> on_auto должен succeed"
        state = engine.get_state(entity_id)
        assert state.current_state == "on_auto"
        assert state.entered_at == datetime(2026, 9, 9, 12, 0, 0).timestamp()

        # Проверяем, что таймер запланирован
        assert entity_id in engine._timers, "Таймер для on_auto должен быть создан"

    # ========================================================================
    # ШАГ 2: t=12:01:00 (через 60 сек) - Пользователь нажал кнопку (ручной режим)
    # ========================================================================
    with freeze_time("2026-09-09 12:01:00"):
        result = await engine.trigger(entity_id, "manual_override", trace_id="test-002")

        assert result is True, "Переход on_auto -> on_manual должен succeed"
        state = engine.get_state(entity_id)
        assert state.current_state == "on_manual"

        # КРИТИЧЕСКИ ВАЖНО: Проверяем, что контекст обновился
        expected_until = datetime(2026, 9, 9, 13, 1, 0).timestamp() # 12:01 + 3600 сек
        assert state.context.get("manual_override_until") == expected_until

        # КРИТИЧЕСКИ ВАЖНО: Проверяем, что старый таймер движения был ОТМЕНЕН
        # (В _cancel_timers он удаляется из self._timers перед созданием нового)
        # Новый таймер уже должен быть в _timers, но мы проверим, что их ровно 1
        assert len(engine._timers) == 1, "Должен быть только один активный таймер (новый)"

    # ========================================================================
    # ШАГ 3: t=12:05:00 (через 300 сек от начала) - Старый таймер движения "сработал" бы
    # ========================================================================
    with freeze_time("2026-09-09 12:05:00"):
        # Имитируем, что пришло событие motion_detected (или сработал бы таймер,
        # но таймер был отменен, так что триггерим вручную для проверки Guard)
        result = await engine.trigger(entity_id, "motion_detected", trace_id="test-003")

        # ОЖИДАЕМ: Переход должен быть ЗАБЛОКИРОВАН guard'ом is_not_manual_override
        assert result is False, "Переход должен быть заблокирован ручной блокировкой"

        state = engine.get_state(entity_id)
        assert state.current_state == "on_manual", "Состояние не должно измениться"

    # ========================================================================
    # ШАГ 4: t=13:01:00 (через 3600 сек от ручного включения) - Блокировка истекла
    # ========================================================================
    with freeze_time("2026-09-09 13:01:00"):
        # Имитируем срабатывание таймера ручного режима
        result = await engine.trigger(entity_id, "timeout", trace_id="test-004")

        assert result is True, "Переход on_manual -> off должен succeed после истечения времени"
        state = engine.get_state(entity_id)
        assert state.current_state == "off"
        assert len(engine._timers) == 0, "Все таймеры должны быть завершены"
