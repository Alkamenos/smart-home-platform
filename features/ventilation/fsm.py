# ============================================================
# FSM: Автомат вентиляции
# Описание состояний и переходов для фичи "Вентиляция"
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
# Константы и пороги
# ============================================================

# Пороги CO2 (ppm)
CO2_NORMAL_MAX = 800
CO2_BOOST_THRESHOLD = 1000
CO2_CRITICAL = 1500

# Пороги влажности (%)
HUMIDITY_NORMAL_MAX = 60
HUMIDITY_BOOST_THRESHOLD = 70

# Температурные пороги для зимней паузы
WINTER_PAUSE_TEMP_OUTDOOR = -10.0


# ============================================================
# Определения автоматов для вентиляции
# ============================================================

# Автомат по умолчанию для рекуператора
VENTILATION_FSM_DEFAULT = {
    "states": ["NORMAL", "BOOST", "NIGHT", "AWAY", "WINTER_PAUSE", "MANUAL_LOCK"],
    "initial": "NORMAL",
    "transitions": [
        # === Переходы из NORMAL ===
        {
            "from": "NORMAL",
            "to": "BOOST",
            "trigger": "high_co2_or_humidity",
            "priority": 30,
            "why": "Высокий CO2 или влажность - усиленная вентиляция"
        },
        {
            "from": "NORMAL",
            "to": "NIGHT",
            "trigger": "night_schedule",
            "priority": 20,
            "why": "Ночное время - пониженный режим"
        },
        {
            "from": "NORMAL",
            "to": "AWAY",
            "trigger": "away_mode",
            "priority": 20,
            "why": "Режим отсутствия - минимальная вентиляция"
        },
        {
            "from": "NORMAL",
            "to": "WINTER_PAUSE",
            "trigger": "winter_conditions",
            "priority": 400,
            "why": "Зимняя пауза - рекуператор заморожен"
        },
        {
            "from": "NORMAL",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство - автоматика заблокирована"
        },
        # === Переходы из BOOST ===
        {
            "from": "BOOST",
            "to": "NORMAL",
            "trigger": "co2_humidity_normal",
            "priority": 10,
            "why": "CO2 и влажность в норме - возврат к обычной вентиляции"
        },
        {
            "from": "BOOST",
            "to": "BOOST",
            "trigger": "boost_timeout_active",
            "priority": 30,
            "why": "Boost продолжается"
        },
        {
            "from": "BOOST",
            "to": "BOOST",
            "trigger": "critical_co2",
            "priority": 50,
            "why": "Критический CO2 или ручной буст - boost продолжается"
        },
        {
            "from": "BOOST",
            "to": "NIGHT",
            "trigger": "night_schedule",
            "priority": 20,
            "why": "Ночное время - переход из boost в ночной режим"
        },
        {
            "from": "BOOST",
            "to": "AWAY",
            "trigger": "away_mode",
            "priority": 20,
            "why": "Режим отсутствия - переход из boost"
        },
        {
            "from": "BOOST",
            "to": "WINTER_PAUSE",
            "trigger": "winter_conditions",
            "priority": 400,
            "why": "Зимняя пауза - переход из boost"
        },
        {
            "from": "BOOST",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство во время boost"
        },
        # === Переходы из NIGHT ===
        {
            "from": "NIGHT",
            "to": "NORMAL",
            "trigger": "day_schedule",
            "priority": 20,
            "why": "Дневное время - выход из ночного режима"
        },
        {
            "from": "NIGHT",
            "to": "BOOST",
            "trigger": "high_co2_or_humidity",
            "priority": 30,
            "why": "Высокий CO2 или влажность - переход из ночи в boost"
        },
        {
            "from": "NIGHT",
            "to": "BOOST",
            "trigger": "critical_co2",
            "priority": 35,
            "why": "Критический CO2 ночью - аварийный boost"
        },
        {
            "from": "NIGHT",
            "to": "AWAY",
            "trigger": "away_mode",
            "priority": 20,
            "why": "Режим отсутствия - переход из ночи"
        },
        {
            "from": "NIGHT",
            "to": "WINTER_PAUSE",
            "trigger": "winter_conditions",
            "priority": 400,
            "why": "Зимняя пауза - переход из ночи"
        },
        {
            "from": "NIGHT",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство ночью"
        },
        # === Переходы из AWAY ===
        {
            "from": "AWAY",
            "to": "NORMAL",
            "trigger": "home_schedule",
            "priority": 20,
            "why": "Присутствие дома - выход из режима отсутствия"
        },
        {
            "from": "AWAY",
            "to": "BOOST",
            "trigger": "high_co2_or_humidity",
            "priority": 30,
            "why": "Высокий CO2 или влажность - переход из away в boost"
        },
        {
            "from": "AWAY",
            "to": "NIGHT",
            "trigger": "night_schedule",
            "priority": 20,
            "why": "Ночное время - переход из away"
        },
        {
            "from": "AWAY",
            "to": "WINTER_PAUSE",
            "trigger": "winter_conditions",
            "priority": 400,
            "why": "Зимняя пауза - переход из away"
        },
        {
            "from": "AWAY",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство в режиме away"
        },
        # === Переходы из WINTER_PAUSE ===
        {
            "from": "WINTER_PAUSE",
            "to": "NORMAL",
            "trigger": "winter_pause_clear",
            "priority": 10,
            "why": "Зимние условия устранены - выход из паузы"
        },
        {
            "from": "WINTER_PAUSE",
            "to": "WINTER_PAUSE",
            "trigger": "winter_conditions_active",
            "priority": 400,
            "why": "Зимние условия сохраняются - пауза продлена"
        },
        {
            "from": "WINTER_PAUSE",
            "to": "MANUAL_LOCK",
            "trigger": "manual_override",
            "priority": 100,
            "why": "Ручное вмешательство во время зимней паузы"
        },
        # === Переходы из MANUAL_LOCK ===
        {
            "from": "MANUAL_LOCK",
            "to": "NORMAL",
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
            "to": "WINTER_PAUSE",
            "trigger": "winter_conditions",
            "priority": 400,
            "why": "Зимняя пауза прерывает ручной режим"
        }
    ]
}

# Кэш зарегистрированных автоматов для устройств вентиляции
_VENT_FSM_REGISTERED = {}


def _vent_fsm_ensure_registered(device_id, fsm_def):
    """Регистрирует автомат для устройства вентиляции, если ещё не зарегистрирован."""
    entity_id = "fan." + device_id
    if entity_id not in _VENT_FSM_REGISTERED:
        fsm_register(entity_id, fsm_def)
        _VENT_FSM_REGISTERED[entity_id] = True


def ventilation_fsm_definition():
    """Возвращает определение автомата для вентиляции."""
    return VENTILATION_FSM_DEFAULT


def _vent_fsm_build_events(ctx):
    """Строит список событий на основе контекста для триггеров."""
    events = []
    
    # Проверяем зимние условия (высокий приоритет)
    outdoor_temp = ctx.get("outdoor_temperature", 0.0)
    heating_lockout = ctx.get("heating_lockout", False)
    
    if outdoor_temp < WINTER_PAUSE_TEMP_OUTDOOR or heating_lockout:
        events.append({"trigger": "winter_conditions", "src": "погода"})
    elif ctx.get("winter_pause_clear"):
        events.append({"trigger": "winter_pause_clear", "src": "погода"})
    
    # Ручное вмешательство
    if ctx.get("manual_mode") and ctx.get("override_remaining_min", 0) > 0:
        events.append({"trigger": "manual_override", "src": "ручное"})
    else:
        events.append({"trigger": "override_expired", "src": "таймер"})
    
    # Режимы комнаты (контекст)
    room_context = ctx.get("room_context", "HOME_DAY")
    is_night = ctx.get("is_night", False)
    
    if room_context == "EMPTY":
        events.append({"trigger": "away_mode", "src": "присутствие"})
    elif room_context in ["HOME_DAY", "HOME_NIGHT", "PARTY", "SLEEPING"]:
        events.append({"trigger": "home_schedule", "src": "присутствие"})
    
    if room_context == "SLEEPING" or is_night:
        events.append({"trigger": "night_schedule", "src": "расписание"})
    else:
        events.append({"trigger": "day_schedule", "src": "расписание"})
    
    # Проверяем CO2 и влажность
    co2 = ctx.get("co2_level", 400)
    humidity = ctx.get("humidity", 50)
    
    if co2 > CO2_CRITICAL or ctx.get("manual_boost"):
        events.append({"trigger": "critical_co2", "src": "датчик" if not ctx.get("manual_boost") else "ручное"})
    elif co2 > CO2_BOOST_THRESHOLD or humidity > HUMIDITY_BOOST_THRESHOLD:
        events.append({"trigger": "high_co2_or_humidity", "src": "датчик"})
    else:
        events.append({"trigger": "co2_humidity_normal", "src": "датчик"})
    
    # Таймер boost
    if ctx.get("boost_remaining_min", 0) > 0:
        events.append({"trigger": "boost_timeout_active", "src": "таймер"})

    # ручной буст / критический CO2 подавляют понижающие триггеры
    for e in events:
        if e.get("trigger") in ("critical_co2", "manual_override"):
            events = [e]
            break
    return events


def ventilation_fsm_run(device_id, ctx):
    """Выполняет шаг FSM для устройства вентиляции используя универсальный движок.
    
    Args:
        device_id: идентификатор устройства вентиляции
        ctx: контекст устройства (CO2, влажность, температура, режимы)
        
    Returns:
        {"state": новое_состояние, "action": действие, "why": причина}
    """
    entity_id = "fan." + device_id
    
    # Получаем определение автомата
    fsm_def = ventilation_fsm_definition()
    
    # Регистрируем автомат если нужно
    _vent_fsm_ensure_registered(device_id, fsm_def)
    
    # Получаем текущее состояние
    current_state = fsm_get_state(entity_id) or "NORMAL"
    
    # Строим список событий
    events = _vent_fsm_build_events(ctx)
    
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
            if new_state == "NORMAL":
                action = {"preset": "Рекуперация", "pct": 40}
            elif new_state == "BOOST":
                action = {"preset": "Приток MAX", "pct": 100}
            elif new_state == "NIGHT":
                action = {"preset": "Рекуперация", "pct": 10}
            elif new_state == "AWAY":
                action = {"preset": "Рекуперация", "pct": 20}
            elif new_state == "WINTER_PAUSE":
                action = {"preset": "OFF"}
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


def ventilation_fsm_get_state(device_id):
    """Получить текущее состояние FSM для устройства вентиляции."""
    entity_id = "fan." + device_id
    return fsm_get_state(entity_id) or "NORMAL"
