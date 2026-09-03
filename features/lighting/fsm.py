# ============================================================
# FSM: Автомат освещения
# Описание состояний и переходов для фичи "Освещение"
# ============================================================

import time

# ============================================
# Движок FSM
# ============================================

def fsm_execute(fsm_def, current_state, ctx, events, previous_state=None):
    """Выполняет один шаг автомата.
    
    Args:
        fsm_def: определение автомата (states, initial, transitions)
        current_state: текущее состояние
        ctx: контекст группы (dark, night, motion, presence, etc.)
        events: список произошедших событий [{'name': 'motion', 'priority': 30}, ...]
        previous_state: предыдущее состояние (для возврата из PREVIOUS)
    
    Returns:
        (new_state, transition_info или None)
    """
    states = fsm_def.get("states", [])
    transitions = fsm_def.get("transitions", [])
    
    if current_state not in states:
        current_state = fsm_def.get("initial", "OFF")
    
    # Собираем все возможные переходы из текущего состояния
    possible_transitions = []
    for t in transitions:
        from_states = t.get("from", [])
        if isinstance(from_states, str):
            if from_states == "*":
                from_states = states  # * означает все состояния
            else:
                from_states = [from_states]
        
        if current_state not in from_states:
            continue
        
        # Проверка guard (условия)
        guard = t.get("guard")
        if guard:
            if guard == "not night" and ctx.get("night"):
                continue
            if guard == "dark or motion_day":
                if not ctx.get("dark") and not ctx.get("motion_day"):
                    continue
            if guard == "away" and not ctx.get("away"):
                continue
            if guard == "room_ok":
                # room_ok = True если room_context не в PARTY/SLEEPING
                room_ctx = ctx.get("room_context", "")
                if room_ctx in ("PARTY", "SLEEPING"):
                    continue
        
        possible_transitions.append(t)
    
    # Если нет переходов - остаёмся в текущем состоянии
    if not possible_transitions:
        return current_state, None
    
    # Сортируем по приоритету (убывание)
    possible_transitions.sort(key=lambda x: x.get("priority", 0), reverse=True)
    
    # Находим первый переход, триггер которого совпадает с событием
    for t in possible_transitions:
        trigger = t.get("trigger", "")
        for ev in events:
            ev_name = ev.get("name", "")
            ev_priority = ev.get("priority", 0)
            
            # Проверка совпадения триггера
            if trigger == ev_name:
                # Дополнительная проверка приоритета события
                if ev_priority >= t.get("priority", 0) - 10:
                    to_state = t["to"]
                    # Обработка специального состояния PREVIOUS
                    if to_state == "PREVIOUS":
                        to_state = previous_state if previous_state and previous_state in states else "OFF"
                    
                    return to_state, {
                        "why": t.get("why", ""),
                        "trigger": trigger,
                        "priority": t.get("priority", 0)
                    }
    
    # Ни один переход не сработал
    return current_state, None


def fsm_build_events(ctx):
    """Строит список событий на основе контекста.
    
    Args:
        ctx: контекст группы
    
    Returns:
        список событий [{'name': ..., 'priority': ...}, ...]
    """
    events = []
    
    # События расписания
    if ctx.get("schedule_on"):
        events.append({"name": "schedule_on", "priority": 20})
    if ctx.get("schedule_off"):
        events.append({"name": "schedule_off", "priority": 20})
    
    # События датчика движения
    if ctx.get("motion"):
        if ctx.get("night") and ctx.get("nightlight_enabled"):
            events.append({"name": "night_motion", "priority": 35})
        else:
            events.append({"name": "motion", "priority": 30})
    
    if ctx.get("no_motion_timeout"):
        events.append({"name": "no_motion_timeout", "priority": 10})
    
    if ctx.get("nightlight_timeout"):
        events.append({"name": "nightlight_timeout", "priority": 10})
    
    # Вечеринка
    if ctx.get("party_mode"):
        events.append({"name": "party_start", "priority": 50})
    elif ctx.get("party_ended"):
        events.append({"name": "party_end", "priority": 50})
    
    # Имитация присутствия
    if ctx.get("imitation_on"):
        events.append({"name": "imitation_on", "priority": 15})
    if ctx.get("imitation_off"):
        events.append({"name": "imitation_off", "priority": 15})
    
    # Ручное вмешательство
    if ctx.get("manual_change"):
        events.append({"name": "manual_change", "priority": 100})
    
    # Таймеры
    if ctx.get("timeout_expired"):
        events.append({"name": "timeout", "priority": 5})
    if ctx.get("override_cleared"):
        events.append({"name": "override_clear", "priority": 50})
    
    return events


# ============================================
# Определения автоматов
# ============================================

# Автомат по умолчанию для группы освещения
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
            "guard": "room_ok",
            "priority": 30,
            "why": "Включение по датчику движения"
        },
        # Датчик движения: выключение (нет движения) - возврат в предыдущее состояние
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
            "guard": "room_ok",
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

# Автомат для группы с ночником (спальня, детская)
LIGHT_FSM_NIGHTLIGHT = {
    "states": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT", "PARTY", "MANUAL_LOCK"],
    "initial": "OFF",
    "transitions": [
        # Расписание: включение на закате/по времени
        {
            "from": ["OFF"],
            "to": "ON_SCHEDULE",
            "trigger": "schedule_on",
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
        # Датчик движения: включение днём
        {
            "from": ["OFF", "ON_SCHEDULE"],
            "to": "ON_MOTION",
            "trigger": "motion",
            "guard": "not night",
            "priority": 30,
            "why": "Включение по датчику движения (день)"
        },
        # Датчик движения: ночник ночью
        {
            "from": ["OFF", "ON_SCHEDULE"],
            "to": "NIGHTLIGHT",
            "trigger": "night_motion",
            "priority": 35,
            "why": "Ночник: минимальная яркость ночью при движении"
        },
        # Ночник: выключение по таймеру
        {
            "from": ["NIGHTLIGHT"],
            "to": "OFF",
            "trigger": "nightlight_timeout",
            "priority": 10,
            "why": "Ночник: таймер истёк"
        },
        # Нет движения: выключение
        {
            "from": ["ON_MOTION"],
            "to": "OFF",
            "trigger": "no_motion_timeout",
            "priority": 10,
            "why": "Выключение по таймеру отсутствия движения"
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
        # Ручное вмешательство: блокировка автоматики
        {
            "from": ["OFF", "ON_SCHEDULE", "ON_MOTION", "NIGHTLIGHT", "PARTY"],
            "to": "MANUAL_LOCK",
            "trigger": "manual_change",
            "priority": 100,
            "why": "Ручное вмешательство — автоматика заблокирована"
        },
        # Таймер блокировки истёк: возврат к OFF
        {
            "from": "MANUAL_LOCK",
            "to": "OFF",
            "trigger": "timeout",
            "priority": 5,
            "why": "Таймер блокировки истёк — возврат к автоматике"
        },
        # Явный сброс блокировки
        {
            "from": "MANUAL_LOCK",
            "to": "OFF",
            "trigger": "override_clear",
            "priority": 50,
            "why": "Явный сброс блокировки"
        }
    ]
}

# Автомат для группы с датчиком движения (коридор, санузел)
LIGHT_FSM_MOTION = {
    "states": ["OFF", "ON_MOTION", "MANUAL_LOCK"],
    "initial": "OFF",
    "transitions": [
        # Датчик движения: включение
        {
            "from": ["OFF"],
            "to": "ON_MOTION",
            "trigger": "motion",
            "guard": "dark or motion_day",
            "priority": 30,
            "why": "Включение по датчику движения"
        },
        # Нет движения: выключение
        {
            "from": ["ON_MOTION"],
            "to": "OFF",
            "trigger": "no_motion_timeout",
            "priority": 10,
            "why": "Выключение по таймеру отсутствия движения"
        },
        # Расписание: принудительное выключение
        {
            "from": ["ON_MOTION"],
            "to": "OFF",
            "trigger": "schedule_off",
            "priority": 25,
            "why": "Выключение по расписанию (ночь)"
        },
        # Ручное вмешательство: блокировка автоматики
        {
            "from": ["OFF", "ON_MOTION"],
            "to": "MANUAL_LOCK",
            "trigger": "manual_change",
            "priority": 100,
            "why": "Ручное вмешательство — автоматика заблокирована"
        },
        # Таймер блокировки истёк: возврат к OFF
        {
            "from": "MANUAL_LOCK",
            "to": "OFF",
            "trigger": "timeout",
            "priority": 5,
            "why": "Таймер блокировки истёк — возврат к автоматике"
        },
        # Явный сброс блокировки
        {
            "from": "MANUAL_LOCK",
            "to": "OFF",
            "trigger": "override_clear",
            "priority": 50,
            "why": "Явный сброс блокировки"
        }
    ]
}

# Автомат для группы с имитацией присутствия
LIGHT_FSM_IMITATION = {
    "states": ["OFF", "ON_SCHEDULE", "ON_IMITATION", "MANUAL_LOCK"],
    "initial": "OFF",
    "transitions": [
        # Расписание: включение на закате/по времени
        {
            "from": ["OFF"],
            "to": "ON_SCHEDULE",
            "trigger": "schedule_on",
            "priority": 20,
            "why": "Включение по расписанию (закат/время)"
        },
        # Расписание: выключение
        {
            "from": ["ON_SCHEDULE", "ON_IMITATION"],
            "to": "OFF",
            "trigger": "schedule_off",
            "priority": 20,
            "why": "Выключение по расписанию"
        },
        # Имитация присутствия: включение
        {
            "from": ["OFF"],
            "to": "ON_IMITATION",
            "trigger": "imitation_on",
            "guard": "away",
            "priority": 15,
            "why": "Имитация присутствия: случайное включение"
        },
        # Имитация присутствия: выключение
        {
            "from": ["ON_IMITATION"],
            "to": "OFF",
            "trigger": "imitation_off",
            "priority": 15,
            "why": "Имитация присутствия: случайное выключение"
        },
        # Ручное вмешательство: блокировка автоматики
        {
            "from": ["OFF", "ON_SCHEDULE", "ON_IMITATION"],
            "to": "MANUAL_LOCK",
            "trigger": "manual_change",
            "priority": 100,
            "why": "Ручное вмешательство — автоматика заблокирована"
        },
        # Таймер блокировки истёк: возврат к OFF
        {
            "from": "MANUAL_LOCK",
            "to": "OFF",
            "trigger": "timeout",
            "priority": 5,
            "why": "Таймер блокировки истёк — возврат к автоматике"
        },
        # Явный сброс блокировки
        {
            "from": "MANUAL_LOCK",
            "to": "OFF",
            "trigger": "override_clear",
            "priority": 50,
            "why": "Явный сброс блокировки"
        }
    ]
}


def light_fsm_definition(g):
    """Возвращает определение автомата для конкретной группы освещения.

    Args:
        g: словарь конфигурации группы из манифеста

    Returns:
        определение автомата (LIGHT_FSM_DEFAULT, LIGHT_FSM_NIGHTLIGHT, 
        LIGHT_FSM_MOTION или LIGHT_FSM_IMITATION)
    """
    features = g.get("features") or {}
    
    # Приоритет специализированных автоматов
    if features.get("motion") and not features.get("nightlight"):
        # Только датчик движения без ночника
        return LIGHT_FSM_MOTION
    
    if features.get("nightlight"):
        # Группа с ночником
        return LIGHT_FSM_NIGHTLIGHT
    
    if features.get("imitation"):
        # Группа с имитацией присутствия
        return LIGHT_FSM_IMITATION
    
    # Автомат по умолчанию
    return LIGHT_FSM_DEFAULT


# ============================================
# Runtime: хранение состояний FSM
# ============================================

# Хранение состояния FSM для каждой группы: {gid: {"state": "OFF", "last_transition": time.time(), "why": ""}}
_LIGHT_FSM_STATE = {}


def light_fsm_get_state(gid):
    """Получает текущее состояние FSM для группы.
    
    Args:
        gid: идентификатор группы
    
    Returns:
        состояние (строка)
    """
    if gid not in _LIGHT_FSM_STATE:
        return "OFF"
    return _LIGHT_FSM_STATE[gid].get("state", "OFF")


def light_fsm_set_state(gid, state, why=""):
    """Устанавливает новое состояние FSM для группы.
    
    Args:
        gid: идентификатор группы
        state: новое состояние
        why: причина перехода
    """
    _LIGHT_FSM_STATE[gid] = {
        "state": state,
        "last_transition": time.monotonic(),
        "why": why
    }


def light_fsm_run(g, ctx):
    """Выполняет шаг FSM для группы освещения.
    
    Args:
        g: конфигурация группы
        ctx: контекст группы (dark, night, motion, presence, etc.)
    
    Returns:
        {"state": новое_состояние, "action": действие, "why": причина} или None
    """
    gid = str(g.get("id"))
    fsm_def = light_fsm_definition(g)
    current_state = light_fsm_get_state(gid)
    
    # Строим события из контекста
    events = fsm_build_events(ctx)
    
    # Выполняем шаг автомата
    new_state, transition_info = fsm_execute(fsm_def, current_state, ctx, events)
    
    # Если состояние изменилось - логируем и сохраняем
    if new_state != current_state and transition_info:
        light_fsm_set_state(gid, new_state, transition_info.get("why", ""))
        
        # Определяем действие на основе состояния
        action = None
        if new_state in ["ON_SCHEDULE", "ON_MOTION", "PARTY"]:
            action = {"on": True, "brightness": "normal"}
        elif new_state == "NIGHTLIGHT":
            action = {"on": True, "brightness": "min"}
        elif new_state == "OFF":
            action = {"on": False}
        elif new_state == "MANUAL_LOCK":
            # Блокировка - не меняем состояние света
            action = None
        
        return {
            "state": new_state,
            "action": action,
            "why": transition_info.get("why", ""),
            "trigger": transition_info.get("trigger", "")
        }
    
    # Состояние не изменилось - возвращем текущее
    return {
        "state": new_state,
        "action": None,
        "why": "нет перехода",
        "trigger": None
    }
