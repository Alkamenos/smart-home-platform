# ============================================================
# FSM: Автомат освещения
# Описание состояний и переходов для фичи "Освещение"
# ============================================================

# Автомат по умолчанию для группы освещения
LIGHT_FSM_DEFAULT = {
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
        # Датчик движения: включение
        {
            "from": ["OFF", "ON_SCHEDULE"],
            "to": "ON_MOTION",
            "trigger": "motion",
            "priority": 30,
            "why": "Включение по датчику движения"
        },
        # Датчик движения: выключение (нет движения)
        {
            "from": ["ON_MOTION"],
            "to": "OFF",
            "trigger": "no_motion_timeout",
            "priority": 10,
            "why": "Выключение по таймеру отсутствия движения"
        },
        # Ночник: включение ночью при движении
        {
            "from": ["OFF", "ON_SCHEDULE"],
            "to": "NIGHTLIGHT",
            "trigger": "night_motion",
            "priority": 35,
            "why": "Ночник: минимальная яркость ночью"
        },
        # Ночник: выключение
        {
            "from": ["NIGHTLIGHT"],
            "to": "OFF",
            "trigger": "nightlight_timeout",
            "priority": 10,
            "why": "Ночник: таймер истёк"
        },
        # Вечеринка: включение
        {
            "from": ["OFF", "ON_SCHEDULE", "ON_MOTION"],
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
        # Таймер блокировки истёк: возврат к автоматике
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
