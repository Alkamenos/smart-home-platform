"""
Kitchen Demo - Минимальный рабочий пример Smart Home Platform v3

Этот скрипт демонстрирует работу платформы локально без HA:
- Датчик движения на кухне включает свет
- Через 5 минут без движения свет выключается
- Ручное вмешательство переключает в MANUAL режим

Запуск: python examples/kitchen_demo.py
"""

import sys
import os
import time

# Добавляем parent directory для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus import EventBus
from core.logger import Logger
from core.fsm import FSMEngine
from adapters.mock_adapter import MockAdapter
from adapters.bridge import ActionBridge, StateSync
from features.lighting import create_lighting_automations


def print_header(text: str):
    """Красивый заголовок"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_event(time_offset: str, event: str, details: str = ""):
    """Вывод события с таймингом"""
    emoji = {
        "motion": "🏃",
        "light_on": "💡",
        "light_off": "⬛",
        "timeout": "⏰",
        "manual": "✋",
        "start": "🚀",
        "end": "✅"
    }
    
    print(f"[{time_offset}] {emoji.get(event, '•')} {event.upper()}")
    if details:
        print(f"         {details}")


def main():
    print_header("KITCHEN DEMO - Smart Home Platform v3")
    
    # 1. Инициализация компонентов
    event_bus = EventBus()
    logger = Logger(component="demo", output=None)
    mock_adapter = MockAdapter()
    fsm_engine = FSMEngine(event_bus, logger)
    
    # 2. Регистрируем автомат для кухни
    automations = create_lighting_automations(["kitchen"])
    for auto in automations:
        fsm_engine.register(auto)
    
    # 3. Подключаем мосты (ActionBridge и StateSync)
    bridge = ActionBridge(event_bus, mock_adapter, logger)
    sync = StateSync(event_bus, fsm_engine, logger)
    
    print_event("00:00", "start", "Платформа запущена. Свет на кухне выключен.")
    
    # Показываем начальное состояние
    state = fsm_engine.get_state("light.kitchen")
    print(f"         FSM состояние: {state.current}")
    
    # 4. Сценарий 1: Обнаружено движение → свет включается
    print_event("00:05", "motion", "Датчик движения сработал")
    
    context_motion = {
        "kitchen_motion_sensor": True,
        "kitchen_motion_enabled": True
    }
    result = fsm_engine.trigger("light.kitchen", "motion_detected", context_motion)
    
    state = fsm_engine.get_state("light.kitchen")
    print_event("00:05", "light_on", f"Свет включён! Переход: OFF → {state.current}")
    print(f"         Причина: {state.entered_why}")
    
    # 5. Сценарий 2: Таймаут 5 минут → свет выключается
    print_event("05:05", "timeout", "Прошло 5 минут без движения")
    
    result = fsm_engine.trigger("light.kitchen", "timeout", {})
    
    state = fsm_engine.get_state("light.kitchen")
    print_event("05:05", "light_off", f"Свет выключен. Переход: ON_MOTION → {state.current}")
    
    # 6. Сценарий 3: Ручное вмешательство
    print_event("05:10", "manual", "Пользователь включил свет вручную")
    
    result = fsm_engine.trigger("light.kitchen", "manual_change", {})
    
    state = fsm_engine.get_state("light.kitchen")
    print_event("05:10", "light_on", f"MANUAL режим активирован: {state.current}")
    print(f"         Приоритет: {state.entered_why}")
    
    # 7. Показываем историю переходов
    print_header("ИСТОРИЯ ПЕРЕХОДОВ")
    
    history = state.history[:5]  # Последние 5 переходов
    for i, entry in enumerate(history, 1):
        duration = ""
        if i < len(history):
            prev_time = history[i-1]['at']
            curr_time = entry['at']
            duration = f" ({int(curr_time - prev_time)}с)"
        
        print(f"{i}. {entry['from']:15} → {entry['to']:15} [{entry['trigger']}] {duration}")
    
    # 8. Показываем команды отправленные в MockAdapter
    print_header("КОМАНДЫ В MOCK ADAPTER")
    
    adapter_history = mock_adapter.get_commands_log()
    if adapter_history:
        for cmd in adapter_history:
            if cmd.get('type') == 'command':
                print(f"  • {cmd['entity_id']}: {cmd['command']} (attributes: {cmd.get('attributes', {})})")
    else:
        print("  (команды не отправлялись)")
    
    print_header("DEMO ЗАВЕРШЕНА")
    print_event("", "end", "Все сценарии выполнены успешно!")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
