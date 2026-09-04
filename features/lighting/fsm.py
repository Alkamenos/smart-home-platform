# ============================================================
# FSM: Автомат освещения
# Описание состояний и переходов для фичи "Освещение"
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
# Определения автоматов для освещения
# ============================================================

LIGHT_FSM_DEFAULT = {
    "states": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT", "PARTY", "MANUAL_LOCK", "UNAVAILABLE"],
    "initial": "OFF",
    "transitions": [
        # Устройство недоступно
        {
            "from": "*",
            "to": "UNAVAILABLE",
            "trigger": "device_unavailable",
            "priority": 0,
            "why": "Устройство недоступно"
        },
        # Устройство восстановлено
        {
            "from": "UNAVAILABLE",
            "to": "OFF",
            "trigger": "device_available",
            "priority": 0,
            "why": "Устройство восстановлено"
        },
        # Расписание: включение на закате/по времени
        {
            "from": ["OFF"],
            "to": "ON_SCHEDULE",
            "trigger": "schedule_on",
            "guard": "room_ok",
            "priority": 20,
            "why": "Включение по расписанию (закат/время)"
        },
        # Расписание: выключение на рассвете/по времени
        {
            "from": ["ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT"],
            "to": "OFF",
            "trigger": "schedule_off",
            "priority": 20,
            "why": "Выключение по расписанию (рассвет/время)"
        },
        # Датчик движения: включение
        {
            "from": ["OFF", "ON_SCHEDULE"],
            "to": "ON_MOTION",
            "trigger": "motion",
            "guard": "room_ok and motion_mode != 'Выкл' and not no_night_auto",
            "priority": 30,
            "why": "Включение по датчику движения"
        },
        # Датчик движения: выключение - возврат в предыдущее состояние
        {
            "from": ["ON_MOTION"],
            "to": "PREVIOUS",
            "trigger": "no_motion_timeout",
            "priority": 10,
            "why": "Выключение по таймеру отсутствия движения — возврат в предыдущее состояние"
        },
        # Ночник: включение ночью при движении
        {
            "from": ["OFF", "ON_SCHEDULE"],
            "to": "NIGHTLIGHT",
            "trigger": "night_motion",
            "guard": "room_ok and motion_mode != 'Выкл' and nightlight_helper_on",
            "priority": 35,
            "why": "Ночник: минимальная яркость ночью"
        },
        # Ночник: выключение - возврат в предыдущее состояние
        {
            "from": ["NIGHTLIGHT"],
            "to": "PREVIOUS",
            "trigger": "nightlight_timeout",
            "priority": 10,
            "why": "Ночник: таймер истёк — возврат в предыдущее состояние"
        },
        # Вечеринка: включение
        {
            "from": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT"],
            "to": "PARTY",
            "trigger": "party_start",
            "priority": 50,
            "why": "Вечеринка: свет не выключается по таймеру"
        },
        # Вечеринка: выключение
        {
            "from": ["PARTY"],
            "to": "OFF",
            "trigger": "party_end",
            "priority": 50,
            "why": "Вечеринка завершена"
        },
        # Имитация присутствия: включение
        {
            "from": ["OFF"],
            "to": "ON_SCHEDULE",
            "trigger": "imitation_on",
            "priority": 15,
            "why": "Имитация присутствия: случайное включение"
        },
        # Имитация присутствия: выключение
        {
            "from": ["ON_SCHEDULE"],
            "to": "OFF",
            "trigger": "imitation_off",
            "priority": 15,
            "why": "Имитация присутствия: случайное выключение"
        },
        # Ручное вмешательство: блокировка автоматики
        {
            "from": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT", "PARTY"],
            "to": "MANUAL_LOCK",
            "trigger": "manual_change",
            "priority": 100,
            "why": "Ручное вмешательство — автоматика заблокирована"
        },
        # Таймер блокировки истёк: возврат к предыдущему состоянию
        {
            "from": "MANUAL_LOCK",
            "to": "PREVIOUS",
            "trigger": "timeout",
            "priority": 5,
            "why": "Таймер блокировки истёк — возврат к предыдущему состоянию"
        },
        # Явный сброс блокировки: возврат к предыдущему состоянию
        {
            "from": "MANUAL_LOCK",
            "to": "PREVIOUS",
            "trigger": "override_clear",
            "priority": 50,
            "why": "Явный сброс блокировки — возврат к предыдущему состоянию"
        }
    ]
}

LIGHT_FSM_NIGHTLIGHT = {
    "states": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT", "PARTY", "MANUAL_LOCK"],
    "initial": "OFF",
    "transitions": [
        {"from": ["OFF"], "to": "ON_SCHEDULE", "trigger": "schedule_on", "priority": 20, "why": "Включение по расписанию"},
        {"from": ["ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT"], "to": "OFF", "trigger": "schedule_off", "priority": 20, "why": "Выключение по расписанию"},
        {"from": ["OFF", "ON_SCHEDULE"], "to": "ON_MOTION", "trigger": "motion", "guard": "not night and motion_mode != 'Выкл' and not no_night_auto", "priority": 30, "why": "Включение по датчику движения (день)"},
        {"from": ["OFF", "ON_SCHEDULE"], "to": "NIGHTLIGHT", "trigger": "night_motion", "guard": "motion_mode != 'Выкл' and nightlight_helper_on", "priority": 35, "why": "Ночник ночью при движении"},
        {"from": ["NIGHTLIGHT"], "to": "OFF", "trigger": "nightlight_timeout", "priority": 10, "why": "Ночник: таймер истёк"},
        {"from": ["ON_MOTION"], "to": "OFF", "trigger": "no_motion_timeout", "priority": 10, "why": "Выключение по таймеру отсутствия движения"},
        {"from": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT"], "to": "PARTY", "trigger": "party_start", "priority": 50, "why": "Вечеринка: свет не выключается"},
        {"from": ["PARTY"], "to": "OFF", "trigger": "party_end", "priority": 50, "why": "Вечеринка завершена"},
        {"from": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT", "PARTY"], "to": "MANUAL_LOCK", "trigger": "manual_change", "priority": 100, "why": "Ручное вмешательство"},
        {"from": "MANUAL_LOCK", "to": "OFF", "trigger": "timeout", "priority": 5, "why": "Таймер блокировки истёк"},
        {"from": "MANUAL_LOCK", "to": "OFF", "trigger": "override_clear", "priority": 50, "why": "Явный сброс блокировки"}
    ]
}

LIGHT_FSM_MOTION = {
    "states": ["OFF", "ON_MOTION", "MANUAL_LOCK"],
    "initial": "OFF",
    "transitions": [
        {"from": ["OFF"], "to": "ON_MOTION", "trigger": "motion", "guard": "(dark or motion_day) and motion_mode != 'Выкл' and not no_night_auto", "priority": 30, "why": "Включение по датчику движения"},
        {"from": ["ON_MOTION"], "to": "OFF", "trigger": "no_motion_timeout", "priority": 10, "why": "Выключение по таймеру отсутствия движения"},
        {"from": ["ON_MOTION"], "to": "OFF", "trigger": "schedule_off", "priority": 25, "why": "Выключение по расписанию (ночь)"},
        {"from": ["OFF", "ON_MOTION"], "to": "MANUAL_LOCK", "trigger": "manual_change", "priority": 100, "why": "Ручное вмешательство"},
        {"from": "MANUAL_LOCK", "to": "OFF", "trigger": "timeout", "priority": 5, "why": "Таймер блокировки истёк"},
        {"from": "MANUAL_LOCK", "to": "OFF", "trigger": "override_clear", "priority": 50, "why": "Явный сброс блокировки"}
    ]
}

LIGHT_FSM_IMITATION = {
    "states": ["OFF", "ON_SCHEDULE", "ON_IMITATION", "MANUAL_LOCK"],
    "initial": "OFF",
    "transitions": [
        {"from": ["OFF"], "to": "ON_SCHEDULE", "trigger": "schedule_on", "priority": 20, "why": "Включение по расписанию"},
        {"from": ["ON_SCHEDULE", "ON_IMITATION"], "to": "OFF", "trigger": "schedule_off", "priority": 20, "why": "Выключение по расписанию"},
        {"from": ["OFF"], "to": "ON_IMITATION", "trigger": "imitation_on", "guard": "away", "priority": 15, "why": "Имитация присутствия: случайное включение"},
        {"from": ["ON_IMITATION"], "to": "OFF", "trigger": "imitation_off", "priority": 15, "why": "Имитация присутствия: случайное выключение"},
        {"from": ["OFF", "ON_SCHEDULE", "ON_IMITATION"], "to": "MANUAL_LOCK", "trigger": "manual_change", "priority": 100, "why": "Ручное вмешательство"},
        {"from": "MANUAL_LOCK", "to": "OFF", "trigger": "timeout", "priority": 5, "why": "Таймер блокировки истёк"},
        {"from": "MANUAL_LOCK", "to": "OFF", "trigger": "override_clear", "priority": 50, "why": "Явный сброс блокировки"}
    ]
}

def light_fsm_definition(g):
    """Возвращает определение автомата для конкретной группы освещения."""
    features = g.get("features") or {}
    
    if features.get("motion") and not features.get("nightlight"):
        return LIGHT_FSM_MOTION
    if features.get("nightlight"):
        return LIGHT_FSM_NIGHTLIGHT
    if features.get("imitation"):
        return LIGHT_FSM_IMITATION
    return LIGHT_FSM_DEFAULT

# ============================================================
# Runtime: хранение состояний и интеграция с универсальным движком
# ============================================================

# Кэш зарегистрированных автоматов для групп
_LIGHT_FSM_REGISTERED = {}

def _light_fsm_ensure_registered(gid, fsm_def):
    """Регистрирует автомат для группы, если ещё не зарегистрирован."""
    entity_id = "light." + gid
    if entity_id not in _LIGHT_FSM_REGISTERED:
        fsm_register(entity_id, fsm_def)
        _LIGHT_FSM_REGISTERED[entity_id] = True

def _light_fsm_build_events(ctx):
    """Строит список событий на основе контекста для триггеров."""
    events = []
    
    if ctx.get("schedule_on"):
        events.append({"trigger": "schedule_on", "src": "расписание"})
    if ctx.get("schedule_off"):
        events.append({"trigger": "schedule_off", "src": "расписание"})
    
    if ctx.get("motion"):
        if ctx.get("night") and ctx.get("nightlight_enabled"):
            events.append({"trigger": "night_motion", "src": "датчик"})
        else:
            events.append({"trigger": "motion", "src": "датчик"})
    
    if ctx.get("no_motion_timeout"):
        events.append({"trigger": "no_motion_timeout", "src": "таймер"})
    if ctx.get("nightlight_timeout"):
        events.append({"trigger": "nightlight_timeout", "src": "таймер"})
    
    if ctx.get("party_mode"):
        events.append({"trigger": "party_start", "src": "режим"})
    elif ctx.get("party_ended"):
        events.append({"trigger": "party_end", "src": "режим"})
    
    if ctx.get("imitation_on"):
        events.append({"trigger": "imitation_on", "src": "имитация"})
    if ctx.get("imitation_off"):
        events.append({"trigger": "imitation_off", "src": "имитация"})
    
    if ctx.get("manual_change"):
        events.append({"trigger": "manual_change", "src": "ручное"})
    
    if ctx.get("timeout_expired"):
        events.append({"trigger": "timeout", "src": "таймер"})
    if ctx.get("override_cleared"):
        events.append({"trigger": "override_clear", "src": "сервис"})
    
    if not ctx.get("device_available"):
        events.append({"trigger": "device_unavailable", "src": "устройство"})
    else:
        current = fsm_get_state("light." + ctx.get("gid", ""))
        if current == "UNAVAILABLE":
            events.append({"trigger": "device_available", "src": "устройство"})
    
    return events

def light_fsm_run(g, ctx):
    """Выполняет шаг FSM для группы освещения используя универсальный движок.
    
    Args:
        g: конфигурация группы
        ctx: контекст группы
        
    Returns:
        {"state": новое_состояние, "action": действие, "why": причина}
    """
    gid = str(g.get("id"))
    entity_id = "light." + gid
    
    # Получаем определение автомата
    fsm_def = light_fsm_definition(g)
    
    # Регистрируем автомат если нужно
    _light_fsm_ensure_registered(gid, fsm_def)
    
    # Получаем текущее состояние
    current_state = fsm_get_state(entity_id) or "OFF"
    
    # Добавляем gid в контекст для обработки device_available
    ctx["gid"] = gid
    
    # Строим список событий
    events = _light_fsm_build_events(ctx)
    
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
            if new_state in ["ON_SCHEDULE", "ON_MOTION", "PARTY"]:
                action = {"on": True, "brightness": "normal"}
            elif new_state == "NIGHTLIGHT":
                action = {"on": True, "brightness": "min"}
            elif new_state == "OFF":
                action = {"on": False}
            
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

def light_fsm_get_state(gid):
    """Получить текущее состояние FSM для группы."""
    entity_id = "light." + gid
    return fsm_get_state(entity_id) or "OFF"
