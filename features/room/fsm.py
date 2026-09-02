# ============================================================
# FSM: Автомат комнаты / дома
# Определяет контекст для всех фич (свет, шторы, климат, вентиляция)
# ============================================================

# Автомат для всего дома (один общий контекст)
ROOM_FSM_HOME = {
    "states": ["EMPTY", "HOME_DAY", "HOME_NIGHT", "PARTY", "SLEEPING"],
    "initial": "HOME_DAY",
    "transitions": [
        # Уход из дома
        {
            "from": ["HOME_DAY", "HOME_NIGHT", "PARTY", "SLEEPING"],
            "to": "EMPTY",
            "trigger": "presence_leave",
            "priority": 50,
            "why": "Все ушли из дома"
        },
        # Приход домой днём
        {
            "from": "EMPTY",
            "to": "HOME_DAY",
            "trigger": "presence_arrive_day",
            "priority": 50,
            "why": "Пришли домой (день)"
        },
        # Приход домой ночью
        {
            "from": "EMPTY",
            "to": "HOME_NIGHT",
            "trigger": "presence_arrive_night",
            "priority": 50,
            "why": "Пришли домой (ночь)"
        },
        # Закат: день → ночь
        {
            "from": "HOME_DAY",
            "to": "HOME_NIGHT",
            "trigger": "sunset",
            "priority": 20,
            "why": "Закат — переход в ночной режим"
        },
        # Рассвет: ночь → день
        {
            "from": "HOME_NIGHT",
            "to": "HOME_DAY",
            "trigger": "sunrise",
            "priority": 20,
            "why": "Рассвет — переход в дневной режим"
        },
        # Вечеринка: включение
        {
            "from": ["HOME_DAY", "HOME_NIGHT"],
            "to": "PARTY",
            "trigger": "party_on",
            "priority": 40,
            "why": "Режим вечеринки включён"
        },
        # Вечеринка: выключение (возврат в текущий режим)
        {
            "from": "PARTY",
            "to": "HOME_NIGHT",
            "trigger": "party_off",
            "priority": 40,
            "why": "Режим вечеринки выключен"
        },
        # Режим сна: включение
        {
            "from": ["HOME_DAY", "HOME_NIGHT"],
            "to": "SLEEPING",
            "trigger": "sleep_on",
            "priority": 45,
            "why": "Режим сна включён"
        },
        # Режим сна: выключение (пробуждение)
        {
            "from": "SLEEPING",
            "to": "HOME_DAY",
            "trigger": "sleep_off",
            "priority": 45,
            "why": "Пробуждение — режим сна выключен"
        },
        # Аварийная ситуация: все должны быть в безопасности
        {
            "from": "*",
            "to": "HOME_DAY",
            "trigger": "emergency",
            "priority": 1000,
            "why": "Аварийная ситуация"
        }
    ]
}


def room_fsm_definition(room_id="main"):
    """Возвращает определение автомата для комнаты.
    
    Сейчас один общий автомат для всего дома.
    Позже можно расширить на отдельные комнаты.
    """
    return ROOM_FSM_HOME
