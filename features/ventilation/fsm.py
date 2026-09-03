"""
FSM для управления вентиляцией.
Состояния: NORMAL, BOOST, NIGHT, AWAY, WINTER_PAUSE, MANUAL_LOCK
Интеграция с heating_lockout и координация с климатом.
"""

from typing import Dict, Any, Optional

# =============================================================================
# КОНСТАНТЫ И СОСТОЯНИЯ
# =============================================================================

VENTILATION_FSM_VERSION = "1.0.0"

# Состояния автомата
STATE_VENT_NORMAL = "NORMAL"           # Нормальная вентиляция по расписанию/CO2
STATE_VENT_BOOST = "BOOST"             # Усиленная вентиляция (высокий CO2, влажность)
STATE_VENT_NIGHT = "NIGHT"             # Ночной режим (пониженный шум)
STATE_VENT_AWAY = "AWAY"               # Режим отсутствия (минимальная вентиляция)
STATE_VENT_WINTER_PAUSE = "WINTER_PAUSE"  # Зимняя пауза (рекуператор заморожен)
STATE_VENT_MANUAL_LOCK = "MANUAL_LOCK"    # Ручное управление (override)

# Приоритеты переходов
PRIORITY_MANUAL = 100
PRIORITY_SAFETY = 500
PRIORITY_HEATING_LOCKOUT = 400
PRIORITY_SCHEDULE = 20
PRIORITY_NORMAL = 10
PRIORITY_EMERGENCY = 1000

# Таймауты (минуты)
BOOST_DURATION_MIN = 30  # Длительность boost режима
WINTER_PAUSE_DURATION_MIN = 60  # Длительность зимней паузы
MANUAL_OVERRIDE_DURATION_MIN = 60  # Длительность ручного override

# Пороги CO2 (ppm)
CO2_NORMAL_MAX = 800
CO2_BOOST_THRESHOLD = 1000
CO2_CRITICAL = 1500

# Пороги влажности (%)
HUMIDITY_NORMAL_MAX = 60
HUMIDITY_BOOST_THRESHOLD = 70

# Температурные пороги для winter pause
WINTER_PAUSE_TEMP_OUTDOOR = -10.0  # Температура улицы для паузы

# =============================================================================
# ОПРЕДЕЛЕНИЕ FSM
# =============================================================================

VENTILATION_FSM_DEFAULT = {
    "name": "ventilation_control",
    "version": VENTILATION_FSM_VERSION,
    "initial_state": STATE_VENT_NORMAL,
    "states": [
        STATE_VENT_NORMAL,
        STATE_VENT_BOOST,
        STATE_VENT_NIGHT,
        STATE_VENT_AWAY,
        STATE_VENT_WINTER_PAUSE,
        STATE_VENT_MANUAL_LOCK,
    ],
    "transitions": [
        # === Переходы из NORMAL ===
        {
            "from": STATE_VENT_NORMAL,
            "to": STATE_VENT_BOOST,
            "priority": PRIORITY_NORMAL,
            "guard": "high_co2_or_humidity",
            "action": "start_boost",
        },
        {
            "from": STATE_VENT_NORMAL,
            "to": STATE_VENT_NIGHT,
            "priority": PRIORITY_SCHEDULE,
            "guard": "night_schedule",
            "action": "enter_night_mode",
        },
        {
            "from": STATE_VENT_NORMAL,
            "to": STATE_VENT_AWAY,
            "priority": PRIORITY_SCHEDULE,
            "guard": "away_mode",
            "action": "enter_away_mode",
        },
        {
            "from": STATE_VENT_NORMAL,
            "to": STATE_VENT_WINTER_PAUSE,
            "priority": PRIORITY_HEATING_LOCKOUT,
            "guard": "winter_conditions",
            "action": "enter_winter_pause",
        },
        {
            "from": STATE_VENT_NORMAL,
            "to": STATE_VENT_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        
        # === Переходы из BOOST ===
        {
            "from": STATE_VENT_BOOST,
            "to": STATE_VENT_NORMAL,
            "priority": PRIORITY_NORMAL,
            "guard": "co2_humidity_normal",
            "action": "exit_boost",
        },
        {
            "from": STATE_VENT_BOOST,
            "to": STATE_VENT_BOOST,
            "priority": PRIORITY_NORMAL,
            "guard": "boost_timeout_active",
            "action": "continue_boost",
        },
        {
            "from": STATE_VENT_BOOST,
            "to": STATE_VENT_NIGHT,
            "priority": PRIORITY_SCHEDULE,
            "guard": "night_schedule",
            "action": "boost_to_night",
        },
        {
            "from": STATE_VENT_BOOST,
            "to": STATE_VENT_AWAY,
            "priority": PRIORITY_SCHEDULE,
            "guard": "away_mode",
            "action": "boost_to_away",
        },
        {
            "from": STATE_VENT_BOOST,
            "to": STATE_VENT_WINTER_PAUSE,
            "priority": PRIORITY_HEATING_LOCKOUT,
            "guard": "winter_conditions",
            "action": "boost_to_winter_pause",
        },
        {
            "from": STATE_VENT_BOOST,
            "to": STATE_VENT_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "boost_to_manual",
        },
        
        # === Переходы из NIGHT ===
        {
            "from": STATE_VENT_NIGHT,
            "to": STATE_VENT_NORMAL,
            "priority": PRIORITY_SCHEDULE,
            "guard": "day_schedule",
            "action": "exit_night_mode",
        },
        {
            "from": STATE_VENT_NIGHT,
            "to": STATE_VENT_BOOST,
            "priority": PRIORITY_NORMAL,
            "guard": "critical_co2",
            "action": "night_boost_emergency",
        },
        {
            "from": STATE_VENT_NIGHT,
            "to": STATE_VENT_AWAY,
            "priority": PRIORITY_SCHEDULE,
            "guard": "away_mode",
            "action": "night_to_away",
        },
        {
            "from": STATE_VENT_NIGHT,
            "to": STATE_VENT_WINTER_PAUSE,
            "priority": PRIORITY_HEATING_LOCKOUT,
            "guard": "winter_conditions",
            "action": "night_to_winter_pause",
        },
        {
            "from": STATE_VENT_NIGHT,
            "to": STATE_VENT_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "night_to_manual",
        },
        
        # === Переходы из AWAY ===
        {
            "from": STATE_VENT_AWAY,
            "to": STATE_VENT_NORMAL,
            "priority": PRIORITY_SCHEDULE,
            "guard": "home_schedule",
            "action": "exit_away_mode",
        },
        {
            "from": STATE_VENT_AWAY,
            "to": STATE_VENT_BOOST,
            "priority": PRIORITY_NORMAL,
            "guard": "high_co2_or_humidity",
            "action": "away_boost",
        },
        {
            "from": STATE_VENT_AWAY,
            "to": STATE_VENT_NIGHT,
            "priority": PRIORITY_SCHEDULE,
            "guard": "night_schedule",
            "action": "away_to_night",
        },
        {
            "from": STATE_VENT_AWAY,
            "to": STATE_VENT_WINTER_PAUSE,
            "priority": PRIORITY_HEATING_LOCKOUT,
            "guard": "winter_conditions",
            "action": "away_to_winter_pause",
        },
        {
            "from": STATE_VENT_AWAY,
            "to": STATE_VENT_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "away_to_manual",
        },
        
        # === Переходы из WINTER_PAUSE ===
        {
            "from": STATE_VENT_WINTER_PAUSE,
            "to": STATE_VENT_NORMAL,
            "priority": PRIORITY_NORMAL,
            "guard": "winter_pause_clear",
            "action": "exit_winter_pause",
        },
        {
            "from": STATE_VENT_WINTER_PAUSE,
            "to": STATE_VENT_WINTER_PAUSE,
            "priority": PRIORITY_HEATING_LOCKOUT,
            "guard": "winter_conditions_active",
            "action": "maintain_winter_pause",
        },
        {
            "from": STATE_VENT_WINTER_PAUSE,
            "to": STATE_VENT_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "pause_to_manual",
        },
        
        # === Переходы из MANUAL_LOCK ===
        {
            "from": STATE_VENT_MANUAL_LOCK,
            "to": STATE_VENT_NORMAL,
            "priority": PRIORITY_NORMAL,
            "guard": "manual_override_expired",
            "action": "exit_manual_mode",
        },
        {
            "from": STATE_VENT_MANUAL_LOCK,
            "to": STATE_VENT_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "refresh_manual_timer",
        },
        {
            "from": STATE_VENT_MANUAL_LOCK,
            "to": STATE_VENT_WINTER_PAUSE,
            "priority": PRIORITY_HEATING_LOCKOUT,
            "guard": "winter_conditions",
            "action": "manual_to_winter_pause",
        },
    ],
}

# =============================================================================
# GUARDS (Условия перехода)
# =============================================================================

def guard_high_co2_or_humidity(ctx: Dict[str, Any]) -> bool:
    """Проверка высокого CO2 или влажности."""
    co2 = ctx.get("co2_level", 400)
    humidity = ctx.get("humidity", 50)
    return co2 > CO2_BOOST_THRESHOLD or humidity > HUMIDITY_BOOST_THRESHOLD


def guard_critical_co2(ctx: Dict[str, Any]) -> bool:
    """Проверка критического уровня CO2."""
    co2 = ctx.get("co2_level", 400)
    return co2 > CO2_CRITICAL


def guard_co2_humidity_normal(ctx: Dict[str, Any]) -> bool:
    """Проверка нормального уровня CO2 и влажности."""
    co2 = ctx.get("co2_level", 400)
    humidity = ctx.get("humidity", 50)
    return co2 <= CO2_NORMAL_MAX and humidity <= HUMIDITY_NORMAL_MAX


def guard_night_schedule(ctx: Dict[str, Any]) -> bool:
    """Проверка ночного времени по расписанию."""
    room_context = ctx.get("room_context", "HOME_DAY")
    is_night = ctx.get("is_night", False)
    return room_context == "SLEEPING" or is_night


def guard_day_schedule(ctx: Dict[str, Any]) -> bool:
    """Проверка дневного времени по расписанию."""
    room_context = ctx.get("room_context", "HOME_DAY")
    is_night = ctx.get("is_night", False)
    return room_context in ["HOME_DAY", "PARTY"] and not is_night


def guard_away_mode(ctx: Dict[str, Any]) -> bool:
    """Проверка режима отсутствия."""
    room_context = ctx.get("room_context", "HOME_DAY")
    return room_context == "EMPTY"


def guard_home_schedule(ctx: Dict[str, Any]) -> bool:
    """Проверка присутствия дома."""
    room_context = ctx.get("room_context", "HOME_DAY")
    return room_context in ["HOME_DAY", "HOME_NIGHT", "PARTY", "SLEEPING"]


def guard_winter_conditions(ctx: Dict[str, Any]) -> bool:
    """Проверка условий для зимней паузы."""
    outdoor_temp = ctx.get("outdoor_temperature", 0)
    heating_lockout = ctx.get("heating_lockout", False)
    
    # Очень низкая температура улицы
    if outdoor_temp < WINTER_PAUSE_TEMP_OUTDOOR:
        return True
    
    # Глобальная блокировка отопления влияет на вентиляцию
    if heating_lockout:
        return True
    
    return False


def guard_winter_conditions_active(ctx: Dict[str, Any]) -> bool:
    """Проверка сохранения зимних условий."""
    return guard_winter_conditions(ctx)


def guard_winter_pause_clear(ctx: Dict[str, Any]) -> bool:
    """Проверка окончания зимних условий."""
    outdoor_temp = ctx.get("outdoor_temperature", 0)
    heating_lockout = ctx.get("heating_lockout", False)
    pause_timer_expired = ctx.get("pause_timer_expired", True)
    
    # Таймер паузы должен истечь
    if not pause_timer_expired:
        return False
    
    # Температура должна подняться
    if outdoor_temp < WINTER_PAUSE_TEMP_OUTDOOR:
        return False
    
    # Блокировка отопления снята
    if heating_lockout:
        return False
    
    return True


def guard_manual_override_active(ctx: Dict[str, Any]) -> bool:
    """Проверка активности ручного управления."""
    manual_mode = ctx.get("manual_mode", False)
    override_remaining_min = ctx.get("override_remaining_min", 0)
    return manual_mode and override_remaining_min > 0


def guard_manual_override_expired(ctx: Dict[str, Any]) -> bool:
    """Проверка истечения ручного управления."""
    return not guard_manual_override_active(ctx)


def guard_boost_timeout_active(ctx: Dict[str, Any]) -> bool:
    """Проверка активного таймера boost."""
    boost_remaining = ctx.get("boost_remaining_min", 0)
    return boost_remaining > 0


# Маппинг имен guards на функции
GUARD_FUNCTIONS = {
    "high_co2_or_humidity": guard_high_co2_or_humidity,
    "critical_co2": guard_critical_co2,
    "co2_humidity_normal": guard_co2_humidity_normal,
    "night_schedule": guard_night_schedule,
    "day_schedule": guard_day_schedule,
    "away_mode": guard_away_mode,
    "home_schedule": guard_home_schedule,
    "winter_conditions": guard_winter_conditions,
    "winter_conditions_active": guard_winter_conditions_active,
    "winter_pause_clear": guard_winter_pause_clear,
    "manual_override_active": guard_manual_override_active,
    "manual_override_expired": guard_manual_override_expired,
    "boost_timeout_active": guard_boost_timeout_active,
}

# =============================================================================
# ACTIONS (Действия при переходе)
# =============================================================================

ACTION_START_BOOST = "start_boost"
ACTION_EXIT_BOOST = "exit_boost"
ACTION_CONTINUE_BOOST = "continue_boost"
ACTION_ENTER_NIGHT_MODE = "enter_night_mode"
ACTION_EXIT_NIGHT_MODE = "exit_night_mode"
ACTION_ENTER_AWAY_MODE = "enter_away_mode"
ACTION_EXIT_AWAY_MODE = "exit_away_mode"
ACTION_ENTER_WINTER_PAUSE = "enter_winter_pause"
ACTION_EXIT_WINTER_PAUSE = "exit_winter_pause"
ACTION_MAINTAIN_WINTER_PAUSE = "maintain_winter_pause"
ACTION_ENTER_MANUAL_MODE = "enter_manual_mode"
ACTION_EXIT_MANUAL_MODE = "exit_manual_mode"
ACTION_REFRESH_MANUAL_TIMER = "refresh_manual_timer"

# Переходы между состояниями
ACTION_BOOST_TO_NIGHT = "boost_to_night"
ACTION_BOOST_TO_AWAY = "boost_to_away"
ACTION_BOOST_TO_WINTER_PAUSE = "boost_to_winter_pause"
ACTION_BOOST_TO_MANUAL = "boost_to_manual"
ACTION_NIGHT_BOOST_EMERGENCY = "night_boost_emergency"
ACTION_NIGHT_TO_AWAY = "night_to_away"
ACTION_NIGHT_TO_WINTER_PAUSE = "night_to_winter_pause"
ACTION_NIGHT_TO_MANUAL = "night_to_manual"
ACTION_AWAY_BOOST = "away_boost"
ACTION_AWAY_TO_NIGHT = "away_to_night"
ACTION_AWAY_TO_WINTER_PAUSE = "away_to_winter_pause"
ACTION_AWAY_TO_MANUAL = "away_to_manual"
ACTION_PAUSE_TO_MANUAL = "pause_to_manual"
ACTION_MANUAL_TO_WINTER_PAUSE = "manual_to_winter_pause"

# Маппинг имен actions на описания
ACTION_DESCRIPTIONS = {
    ACTION_START_BOOST: "Запуск усиленной вентиляции",
    ACTION_EXIT_BOOST: "Выход из усиленной вентиляции",
    ACTION_CONTINUE_BOOST: "Продление усиленной вентиляции",
    ACTION_ENTER_NIGHT_MODE: "Вход в ночной режим",
    ACTION_EXIT_NIGHT_MODE: "Выход из ночного режима",
    ACTION_ENTER_AWAY_MODE: "Вход в режим отсутствия",
    ACTION_EXIT_AWAY_MODE: "Выход из режима отсутствия",
    ACTION_ENTER_WINTER_PAUSE: "Вход в зимнюю паузу",
    ACTION_EXIT_WINTER_PAUSE: "Выход из зимней паузы",
    ACTION_MAINTAIN_WINTER_PAUSE: "Продление зимней паузы",
    ACTION_ENTER_MANUAL_MODE: "Вход в ручной режим",
    ACTION_EXIT_MANUAL_MODE: "Выход из ручного режима",
    ACTION_REFRESH_MANUAL_TIMER: "Обновление таймера ручного режима",
    ACTION_BOOST_TO_NIGHT: "Переход из boost в night",
    ACTION_BOOST_TO_AWAY: "Переход из boost в away",
    ACTION_BOOST_TO_WINTER_PAUSE: "Переход из boost в winter pause",
    ACTION_BOOST_TO_MANUAL: "Переход из boost в manual",
    ACTION_NIGHT_BOOST_EMERGENCY: "Аварийный boost из night",
    ACTION_NIGHT_TO_AWAY: "Переход из night в away",
    ACTION_NIGHT_TO_WINTER_PAUSE: "Переход из night в winter pause",
    ACTION_NIGHT_TO_MANUAL: "Переход из night в manual",
    ACTION_AWAY_BOOST: "Boost из away",
    ACTION_AWAY_TO_NIGHT: "Переход из away в night",
    ACTION_AWAY_TO_WINTER_PAUSE: "Переход из away в winter pause",
    ACTION_AWAY_TO_MANUAL: "Переход из away в manual",
    ACTION_PAUSE_TO_MANUAL: "Переход из pause в manual",
    ACTION_MANUAL_TO_WINTER_PAUSE: "Переход из manual в winter pause",
}

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def get_fsm_definition() -> Dict[str, Any]:
    """Получить определение FSM вентиляции."""
    return VENTILATION_FSM_DEFAULT


def get_guard_function(guard_name: str):
    """Получить функцию guard по имени."""
    return GUARD_FUNCTIONS.get(guard_name)


def evaluate_guards(transitions: list, ctx: Dict[str, Any]) -> list:
    """
    Оценить все переходы и вернуть подходящие.
    
    Args:
        transitions: Список переходов из текущего состояния
        ctx: Контекст (CO2, влажность, температура, флаги)
    
    Returns:
        Список кортежей (priority, transition) отсортированных по приоритету
    """
    suitable = []
    
    for transition in transitions:
        guard_name = transition.get("guard")
        
        if guard_name is None:
            suitable.append((transition.get("priority", 0), transition))
            continue
        
        guard_func = get_guard_function(guard_name)
        if guard_func and guard_func(ctx):
            suitable.append((transition.get("priority", 0), transition))
    
    suitable.sort(key=lambda x: x[0], reverse=True)
    return suitable


def build_context(
    zone_id: str,
    co2_level: int = 400,
    humidity: float = 50.0,
    outdoor_temperature: float = 0.0,
    indoor_temperature: float = 22.0,
    room_context: str = "HOME_DAY",
    is_night: bool = False,
    manual_mode: bool = False,
    override_remaining_min: int = 0,
    heating_lockout: bool = False,
    boost_remaining_min: int = 0,
    pause_timer_expired: bool = True,
) -> Dict[str, Any]:
    """
    Построить контекст для оценки guards.
    
    Args:
        zone_id: Идентификатор зоны
        co2_level: Уровень CO2 в ppm
        humidity: Влажность в %
        outdoor_temperature: Температура улицы
        indoor_temperature: Температура в помещении
        room_context: Контекст комнаты (EMPTY, HOME_DAY, SLEEPING, PARTY)
        is_night: Ночное время (sun.sun below_horizon)
        manual_mode: Активен ли ручной режим
        override_remaining_min: Осталось минут ручного управления
        heating_lockout: Глобальная блокировка отопления
        boost_remaining_min: Осталось минут boost режима
        pause_timer_expired: Истек ли таймер зимней паузы
    
    Returns:
        Словарь контекста для FSM
    """
    return {
        "zone_id": zone_id,
        "co2_level": co2_level,
        "humidity": humidity,
        "outdoor_temperature": outdoor_temperature,
        "indoor_temperature": indoor_temperature,
        "room_context": room_context,
        "is_night": is_night,
        "manual_mode": manual_mode,
        "override_remaining_min": override_remaining_min,
        "heating_lockout": heating_lockout,
        "boost_remaining_min": boost_remaining_min,
        "pause_timer_expired": pause_timer_expired,
    }


def log_action(action_name: str, zone_id: str, reason: str = "") -> str:
    """
    Сформировать сообщение лога для действия.
    
    Args:
        action_name: Имя действия
        zone_id: Идентификатор зоны
        reason: Причина действия
    
    Returns:
        Форматированная строка лога
    """
    description = ACTION_DESCRIPTIONS.get(action_name, action_name)
    if reason:
        return f"[ventilation][{zone_id}] {description}: {reason}"
    return f"[ventilation][{zone_id}] {description}"
