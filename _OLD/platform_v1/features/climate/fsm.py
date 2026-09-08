# ============================================================
# FSM: Автомат климата
# Описание состояний и переходов для фичи "Климат"
# Использует универсальный движок из ha/pyscript/fsm_engine.py
# ============================================================

# Импорт функций универсального движка
# В реальном окружении они доступны глобально после конкатенации
# В тестах - импортируем напрямую
try:
    fsm_register
except NameError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ha" / "pyscript"))
    from fsm_engine import fsm_register, fsm_trigger, fsm_get_state, _FSM_STATES


# ============================================================
# Определения автоматов для климата
# ============================================================

# Автомат по умолчанию для зоны климата
CLIMATE_FSM_DEFAULT = {
    "states": ["IDLE", "HEATING", "COOLING", "SAFETY_LOCKOUT", "MANUAL_LOCK"],
    "initial": "IDLE",
    "transitions": [
        # === Переходы из IDLE ===
        {
            "from": "IDLE",
            "to": "HEATING",
            "trigger": "needs_heating",
            "priority": 10,
            "why": "Температура ниже уставки - запуск нагрева"
        },
        {
            "from": "IDLE",
            "to": "COOLING",
            "trigger": "needs_cooling",
            "priority": 10,
            "why": "Температура выше уставки - запуск охлаждения"
        },
        {
            "from": "IDLE",
            "to": "SAFETY_LOCKOUT",
            "trigger": "safety_violation",
            "priority": 500,
            "why": "Нарушение безопасности (ошибка датчика, перегрев)"
        },
        {
            "from": "IDLE",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство - автоматика заблокирована"
        },
        # === Переходы из HEATING ===
        {
            "from": "HEATING",
            "to": "IDLE",
            "trigger": "target_reached",
            "priority": 10,
            "why": "Целевая температура достигнута - остановка нагрева"
        },
        {
            "from": "HEATING",
            "to": "COOLING",
            "trigger": "needs_cooling",
            "priority": 10,
            "why": "Переключение с нагрева на охлаждение"
        },
        {
            "from": "HEATING",
            "to": "SAFETY_LOCKOUT",
            "trigger": "safety_violation",
            "priority": 500,
            "why": "Нарушение безопасности во время нагрева"
        },
        {
            "from": "HEATING",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство во время нагрева"
        },
        # === Переходы из COOLING ===
        {
            "from": "COOLING",
            "to": "IDLE",
            "trigger": "target_reached",
            "priority": 10,
            "why": "Целевая температура достигнута - остановка охлаждения"
        },
        {
            "from": "COOLING",
            "to": "HEATING",
            "trigger": "needs_heating",
            "priority": 10,
            "why": "Переключение с охлаждения на нагрев"
        },
        {
            "from": "COOLING",
            "to": "SAFETY_LOCKOUT",
            "trigger": "safety_violation",
            "priority": 500,
            "why": "Нарушение безопасности во время охлаждения"
        },
        {
            "from": "COOLING",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство во время охлаждения"
        },
        # === Переходы из SAFETY_LOCKOUT ===
        {
            "from": "SAFETY_LOCKOUT",
            "to": "IDLE",
            "trigger": "safety_clear",
            "priority": 10,
            "why": "Нарушение безопасности устранено - возврат к автоматике"
        },
        {
            "from": "SAFETY_LOCKOUT",
            "to": "SAFETY_LOCKOUT",
            "trigger": "safety_still_violated",
            "priority": 1000,
            "why": "Нарушение безопасности сохраняется - блокировка продлена"
        },
        # === Переходы из MANUAL_LOCK ===
        {
            "from": "MANUAL_LOCK",
            "to": "IDLE",
            "trigger": "override_expired",
            "priority": 10,
            "why": "Таймер блокировки истёк - возврат к автоматике"
        },
        {
            "from": "MANUAL_LOCK",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство продолжается - таймер обновлён"
        },
        {
            "from": "MANUAL_LOCK",
            "to": "SAFETY_LOCKOUT",
            "trigger": "safety_violation",
            "priority": 500,
            "why": "Нарушение безопасности прерывает ручной режим"
        }
    ]
}

# Кэш зарегистрированных автоматов для зон
_CLIMATE_FSM_REGISTERED = {}


def _climate_fsm_ensure_registered(zone_id, fsm_def):
    """Регистрирует автомат для зоны, если ещё не зарегистрирован."""
    entity_id = "climate." + zone_id
    if entity_id not in _CLIMATE_FSM_REGISTERED:
        fsm_register(entity_id, fsm_def)
        _CLIMATE_FSM_REGISTERED[entity_id] = True


def climate_fsm_definition(room_context="HOME_DAY"):
    """Возвращает определение автомата в зависимости от контекста комнаты."""
    # Сейчас все режимы используют один автомат
    # В будущем можно добавить разные уставки для AWAY, SLEEPING, PARTY
    return CLIMATE_FSM_DEFAULT


def _climate_fsm_build_events(ctx):
    """Строит список событий на основе контекста для триггеров."""
    events = []
    
    # События безопасности (высокий приоритет)
    if ctx.get("sensor_error") or ctx.get("heating_lockout"):
        events.append({"trigger": "safety_violation", "src": "безопасность"})
        # return events  # Early return: предотвращает сравнение None с float ниже
    elif ctx.get("safety_clear"):
        events.append({"trigger": "safety_clear", "src": "безопасность"})
    
    # Ручное вмешательство
    if ctx.get("manual_mode") and ctx.get("override_remaining_min", 0) > 0:
        events.append({"trigger": "manual_override", "src": "ручное"})
    elif ctx.get("override_expired"):
        events.append({"trigger": "override_expired", "src": "таймер"})
    
    # Потребность в нагреве/охлаждении
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp = ctx.get("target_temperature", 22.0)
    hysteresis = ctx.get("temp_hysteresis", 0.5)
    
    if current_temp < (target_temp - hysteresis):
        events.append({"trigger": "needs_heating", "src": "датчик"})
    elif current_temp > (target_temp + hysteresis):
        events.append({"trigger": "needs_cooling", "src": "датчик"})
    else:
        events.append({"trigger": "target_reached", "src": "датчик"})
    
    return events


def climate_fsm_run(zone_id, ctx):
    """Выполняет шаг FSM для зоны климата используя универсальный движок.
    
    Args:
        zone_id: идентификатор зоны
        ctx: контекст зоны (температуры, флаги, режимы)
        
    Returns:
        {"state": новое_состояние, "action": действие, "why": причина}
    """
    entity_id = "climate." + zone_id
    
    # Получаем определение автомата
    room_context = ctx.get("room_context", "HOME_DAY")
    fsm_def = climate_fsm_definition(room_context)
    
    # Регистрируем автомат если нужно
    _climate_fsm_ensure_registered(zone_id, fsm_def)
    
    # Получаем текущее состояние
    current_state = fsm_get_state(entity_id) or "IDLE"
    
    # Строим список событий
    events = _climate_fsm_build_events(ctx)
    
    # Пробуем каждый триггер по приоритету
    for event in events:
        trigger = event["trigger"]
        src = event.get("src", "автоматика")
        
        # Пытаемся триггерить переход
        if fsm_trigger(entity_id, trigger, src=src):
            # Переход произошёл
            new_state = fsm_get_state(entity_id)
            entry = _FSM_STATES.get(entity_id, {})
            why = entry.get("entered_why", "")
            
            # Определяем действие на основе состояния
            action = None
            if new_state == "HEATING":
                action = {"hvac_mode": "heat"}
            elif new_state == "COOLING":
                action = {"hvac_mode": "cool"}
            elif new_state == "IDLE":
                action = {"hvac_mode": "off"}
            elif new_state == "SAFETY_LOCKOUT":
                action = {"hvac_mode": "off", "lockout": True}
            elif new_state == "MANUAL_LOCK":
                action = None  # Не меняем состояние устройства
            
            return {
                "state": new_state,
                "action": action,
                "why": why,
                "trigger": trigger
            }
    
    # Нет переходов - возвращаем текущее состояние
    return {
        "state": current_state,
        "action": None,
        "why": "нет перехода",
        "trigger": None
    }


def climate_fsm_get_state(zone_id):
    """Получить текущее состояние FSM для зоны."""
    entity_id = "climate." + zone_id
    return fsm_get_state(entity_id) or "IDLE"
