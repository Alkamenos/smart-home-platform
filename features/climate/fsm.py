"""
FSM для управления климатом (Heating/Cooling).
Состояния: IDLE, HEATING, COOLING, SAFETY_LOCKOUT, MANUAL_LOCK
Приоритеты переходов: manual(100) > safety(500) > schedule(20) > normal(10)
"""

from typing import Dict, Any, Optional

# =============================================================================
# КОНСТАНТЫ И СОСТОЯНИЯ
# =============================================================================

CLIMATE_FSM_VERSION = "1.0.0"

# Состояния автомата
STATE_CLIMATE_IDLE = "IDLE"              # Целевая температура достигнута
STATE_CLIMATE_HEATING = "HEATING"        # Активный нагрев
STATE_CLIMATE_COOLING = "COOLING"        # Активное охлаждение
STATE_CLIMATE_SAFETY_LOCKOUT = "SAFETY_LOCKOUT"  # Блокировка по безопасности (перегрев, ошибка датчика)
STATE_CLIMATE_MANUAL_LOCK = "MANUAL_LOCK"        # Ручное управление (override)

# Приоритеты переходов
PRIORITY_MANUAL = 100
PRIORITY_SAFETY = 500
PRIORITY_SCHEDULE = 20
PRIORITY_NORMAL = 10
PRIORITY_EMERGENCY = 1000

# Таймауты (минуты)
LOCKOUT_DURATION_MIN = 30  # Длительность блокировки безопасности
MANUAL_OVERRIDE_DURATION_MIN = 60  # Длительность ручного overrides

# Пороги температур (градусы C)
TEMP_HYSTERESIS = 0.5  # Гистерезис для предотвращения частых переключений
SAFETY_MAX_TEMP = 35.0  # Максимальная безопасная температура
SAFETY_MIN_TEMP = 5.0   # Минимальная безопасная температура

# =============================================================================
# ОПРЕДЕЛЕНИЕ FSM
# =============================================================================

CLIMATE_FSM_DEFAULT = {
    "name": "climate_control",
    "version": CLIMATE_FSM_VERSION,
    "initial_state": STATE_CLIMATE_IDLE,
    "states": [
        STATE_CLIMATE_IDLE,
        STATE_CLIMATE_HEATING,
        STATE_CLIMATE_COOLING,
        STATE_CLIMATE_SAFETY_LOCKOUT,
        STATE_CLIMATE_MANUAL_LOCK,
    ],
    "transitions": [
        # === Переходы из IDLE ===
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_HEATING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_heating",
            "action": "start_heating",
        },
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_COOLING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_cooling",
            "action": "start_cooling",
        },
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "trigger_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        
        # === Переходы из HEATING ===
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_heating",
        },
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_COOLING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_cooling",
            "action": "switch_to_cooling",
        },
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "trigger_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        
        # === Переходы из COOLING ===
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_cooling",
        },
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_HEATING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_heating",
            "action": "switch_to_heating",
        },
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "trigger_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        
        # === Переходы из SAFETY_LOCKOUT ===
        {
            "from": STATE_CLIMATE_SAFETY_LOCKOUT,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "safety_clear",
            "action": "clear_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_SAFETY_LOCKOUT,
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_EMERGENCY,
            "guard": "safety_still_violated",
            "action": "maintain_lockout",
        },
        
        # === Переходы из MANUAL_LOCK ===
        {
            "from": STATE_CLIMATE_MANUAL_LOCK,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "manual_override_expired",
            "action": "exit_manual_mode",
        },
        {
            "from": STATE_CLIMATE_MANUAL_LOCK,
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "refresh_manual_timer",
        },
        {
            "from": STATE_CLIMATE_MANUAL_LOCK,
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "safety_interrupts_manual",
        },
    ],
}

# FSM для режима "Away" (экономный)
CLIMATE_FSM_AWAY = {
    "name": "climate_away",
    "version": CLIMATE_FSM_VERSION,
    "initial_state": STATE_CLIMATE_IDLE,
    "states": CLIMATE_FSM_DEFAULT["states"],
    "transitions": [
        # Упрощенные переходы с расширенными гистерезисами
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_HEATING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_heating_away",
            "action": "start_heating",
        },
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_COOLING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_cooling_away",
            "action": "start_cooling",
        },
        # Возврат из HEATING/COOLING в IDLE
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_heating",
        },
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_cooling",
        },
        # Safety переходы
        {
            "from": "*",
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "trigger_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_SAFETY_LOCKOUT,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "safety_clear",
            "action": "clear_safety_lockout",
        },
        # Manual override
        {
            "from": "*",
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        {
            "from": STATE_CLIMATE_MANUAL_LOCK,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "manual_override_expired",
            "action": "exit_manual_mode",
        },
    ],
}

# FSM для режима "Sleeping" (ночной)
CLIMATE_FSM_SLEEPING = {
    "name": "climate_sleeping",
    "version": CLIMATE_FSM_VERSION,
    "initial_state": STATE_CLIMATE_IDLE,
    "states": CLIMATE_FSM_DEFAULT["states"],
    "transitions": [
        # Ночные уставки (комфортная температура для сна)
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_HEATING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_heating_sleep",
            "action": "start_heating",
        },
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_COOLING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_cooling_sleep",
            "action": "start_cooling",
        },
        # Возврат из HEATING/COOLING в IDLE
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_heating",
        },
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_cooling",
        },
        # Safety переходы
        {
            "from": "*",
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "trigger_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_SAFETY_LOCKOUT,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "safety_clear",
            "action": "clear_safety_lockout",
        },
        # Manual override
        {
            "from": "*",
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        {
            "from": STATE_CLIMATE_MANUAL_LOCK,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "manual_override_expired",
            "action": "exit_manual_mode",
        },
    ],
}

# FSM для режима "Party" (повышенный комфорт)
CLIMATE_FSM_PARTY = {
    "name": "climate_party",
    "version": CLIMATE_FSM_VERSION,
    "initial_state": STATE_CLIMATE_IDLE,
    "states": CLIMATE_FSM_DEFAULT["states"],
    "transitions": [
        # Уставки для вечеринки (более точное поддержание температуры)
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_HEATING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_heating_party",
            "action": "start_heating",
        },
        {
            "from": STATE_CLIMATE_IDLE,
            "to": STATE_CLIMATE_COOLING,
            "priority": PRIORITY_NORMAL,
            "guard": "needs_cooling_party",
            "action": "start_cooling",
        },
        # Возврат из HEATING/COOLING в IDLE
        {
            "from": STATE_CLIMATE_HEATING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_heating",
        },
        {
            "from": STATE_CLIMATE_COOLING,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "target_reached",
            "action": "stop_cooling",
        },
        # Safety переходы
        {
            "from": "*",
            "to": STATE_CLIMATE_SAFETY_LOCKOUT,
            "priority": PRIORITY_SAFETY,
            "guard": "safety_violation",
            "action": "trigger_safety_lockout",
        },
        {
            "from": STATE_CLIMATE_SAFETY_LOCKOUT,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "safety_clear",
            "action": "clear_safety_lockout",
        },
        # Manual override
        {
            "from": "*",
            "to": STATE_CLIMATE_MANUAL_LOCK,
            "priority": PRIORITY_MANUAL,
            "guard": "manual_override_active",
            "action": "enter_manual_mode",
        },
        {
            "from": STATE_CLIMATE_MANUAL_LOCK,
            "to": STATE_CLIMATE_IDLE,
            "priority": PRIORITY_NORMAL,
            "guard": "manual_override_expired",
            "action": "exit_manual_mode",
        },
    ],
}

# =============================================================================
# GUARDS (Условия перехода)
# =============================================================================

def guard_needs_heating(ctx: Dict[str, Any]) -> bool:
    """Проверка необходимости нагрева."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp = ctx.get("target_temperature", 22.0)
    return current_temp < (target_temp - TEMP_HYSTERESIS)


def guard_needs_cooling(ctx: Dict[str, Any]) -> bool:
    """Проверка необходимости охлаждения."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp = ctx.get("target_temperature", 22.0)
    return current_temp > (target_temp + TEMP_HYSTERESIS)


def guard_target_reached(ctx: Dict[str, Any]) -> bool:
    """Проверка достижения целевой температуры."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp = ctx.get("target_temperature", 22.0)
    mode = ctx.get("hvac_mode", "heat")  # heat, cool, auto
    
    if mode == "heat":
        return current_temp >= target_temp
    elif mode == "cool":
        return current_temp <= target_temp
    else:
        return (target_temp - TEMP_HYSTERESIS) <= current_temp <= (target_temp + TEMP_HYSTERESIS)


def guard_safety_violation(ctx: Dict[str, Any]) -> bool:
    """Проверка нарушения безопасности."""
    current_temp = ctx.get("current_temperature", 20.0)
    sensor_error = ctx.get("sensor_error", False)
    heating_lockout = ctx.get("heating_lockout", False)
    
    # Перегрев или переохлаждение
    if current_temp > SAFETY_MAX_TEMP or current_temp < SAFETY_MIN_TEMP:
        return True
    
    # Ошибка датчика
    if sensor_error:
        return True
    
    # Глобальная блокировка отопления (пожарная безопасность)
    if heating_lockout:
        return True
    
    return False


def guard_safety_clear(ctx: Dict[str, Any]) -> bool:
    """Проверка устранения нарушения безопасности."""
    current_temp = ctx.get("current_temperature", 20.0)
    sensor_error = ctx.get("sensor_error", False)
    heating_lockout = ctx.get("heating_lockout", False)
    lockout_timer_expired = ctx.get("lockout_timer_expired", True)
    
    # Таймер блокировки должен истечь
    if not lockout_timer_expired:
        return False
    
    # Температура в норме
    if current_temp > SAFETY_MAX_TEMP or current_temp < SAFETY_MIN_TEMP:
        return False
    
    # Нет ошибки датчика
    if sensor_error:
        return False
    
    # Нет глобальной блокировки
    if heating_lockout:
        return False
    
    return True


def guard_safety_still_violated(ctx: Dict[str, Any]) -> bool:
    """Проверка сохранения нарушения безопасности."""
    return not guard_safety_clear(ctx)


def guard_manual_override_active(ctx: Dict[str, Any]) -> bool:
    """Проверка активности ручного управления."""
    manual_mode = ctx.get("manual_mode", False)
    override_remaining = ctx.get("override_remaining_min", 0)
    return manual_mode and override_remaining > 0


def guard_manual_override_expired(ctx: Dict[str, Any]) -> bool:
    """Проверка истечения ручного управления."""
    return not guard_manual_override_active(ctx)


# Специализированные guards для разных режимов комнаты
def guard_needs_heating_away(ctx: Dict[str, Any]) -> bool:
    """Нагрев в режиме Away (экономный, lower target)."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp_away = ctx.get("target_temperature_away", 18.0)
    return current_temp < (target_temp_away - TEMP_HYSTERESIS - 1.0)  # Больший гистерезис


def guard_needs_cooling_away(ctx: Dict[str, Any]) -> bool:
    """Охлаждение в режиме Away (экономный, higher target)."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp_away = ctx.get("target_temperature_away", 26.0)
    return current_temp > (target_temp_away + TEMP_HYSTERESIS + 1.0)


def guard_needs_heating_sleep(ctx: Dict[str, Any]) -> bool:
    """Нагрев в режиме Sleeping (комфорт для сна)."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp_sleep = ctx.get("target_temperature_sleep", 20.0)
    return current_temp < (target_temp_sleep - TEMP_HYSTERESIS)


def guard_needs_cooling_sleep(ctx: Dict[str, Any]) -> bool:
    """Охлаждение в режиме Sleeping."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp_sleep = ctx.get("target_temperature_sleep", 20.0)
    return current_temp > (target_temp_sleep + TEMP_HYSTERESIS)


def guard_needs_heating_party(ctx: Dict[str, Any]) -> bool:
    """Нагрев в режиме Party (точный контроль)."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp_party = ctx.get("target_temperature_party", 22.0)
    return current_temp < (target_temp_party - TEMP_HYSTERESIS / 2)  # Меньший гистерезис


def guard_needs_cooling_party(ctx: Dict[str, Any]) -> bool:
    """Охлаждение в режиме Party."""
    current_temp = ctx.get("current_temperature", 20.0)
    target_temp_party = ctx.get("target_temperature_party", 22.0)
    return current_temp > (target_temp_party + TEMP_HYSTERESIS / 2)


# Маппинг имен guards на функции
GUARD_FUNCTIONS = {
    "needs_heating": guard_needs_heating,
    "needs_cooling": guard_needs_cooling,
    "target_reached": guard_target_reached,
    "safety_violation": guard_safety_violation,
    "safety_clear": guard_safety_clear,
    "safety_still_violated": guard_safety_still_violated,
    "manual_override_active": guard_manual_override_active,
    "manual_override_expired": guard_manual_override_expired,
    "needs_heating_away": guard_needs_heating_away,
    "needs_cooling_away": guard_needs_cooling_away,
    "needs_heating_sleep": guard_needs_heating_sleep,
    "needs_cooling_sleep": guard_needs_cooling_sleep,
    "needs_heating_party": guard_needs_heating_party,
    "needs_cooling_party": guard_needs_cooling_party,
}

# =============================================================================
# ACTIONS (Действия при переходе)
# =============================================================================

ACTION_START_HEATING = "start_heating"
ACTION_STOP_HEATING = "stop_heating"
ACTION_START_COOLING = "start_cooling"
ACTION_STOP_COOLING = "stop_cooling"
ACTION_SWITCH_TO_HEATING = "switch_to_heating"
ACTION_SWITCH_TO_COOLING = "switch_to_cooling"
ACTION_TRIGGER_SAFETY_LOCKOUT = "trigger_safety_lockout"
ACTION_CLEAR_SAFETY_LOCKOUT = "clear_safety_lockout"
ACTION_MAINTAIN_LOCKOUT = "maintain_lockout"
ACTION_ENTER_MANUAL_MODE = "enter_manual_mode"
ACTION_EXIT_MANUAL_MODE = "exit_manual_mode"
ACTION_REFRESH_MANUAL_TIMER = "refresh_manual_timer"
ACTION_SAFETY_INTERRUPTS_MANUAL = "safety_interrupts_manual"

# Маппинг имен actions на описания
ACTION_DESCRIPTIONS = {
    ACTION_START_HEATING: "Включение нагрева",
    ACTION_STOP_HEATING: "Выключение нагрева",
    ACTION_START_COOLING: "Включение охлаждения",
    ACTION_STOP_COOLING: "Выключение охлаждения",
    ACTION_SWITCH_TO_HEATING: "Переключение с охлаждения на нагрев",
    ACTION_SWITCH_TO_COOLING: "Переключение с нагрева на охлаждение",
    ACTION_TRIGGER_SAFETY_LOCKOUT: "Активация блокировки безопасности",
    ACTION_CLEAR_SAFETY_LOCKOUT: "Снятие блокировки безопасности",
    ACTION_MAINTAIN_LOCKOUT: "Продление блокировки безопасности",
    ACTION_ENTER_MANUAL_MODE: "Вход в ручной режим",
    ACTION_EXIT_MANUAL_MODE: "Выход из ручного режима",
    ACTION_REFRESH_MANUAL_TIMER: "Обновление таймера ручного режима",
    ACTION_SAFETY_INTERRUPTS_MANUAL: "Прерывание ручного режима по безопасности",
}

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def get_fsm_definition(mode: str = "default") -> Dict[str, Any]:
    """
    Получить определение FSM для указанного режима.
    
    Args:
        mode: Режим работы ("default", "away", "sleeping", "party")
    
    Returns:
        Словарь с определением FSM
    """
    fsm_map = {
        "default": CLIMATE_FSM_DEFAULT,
        "away": CLIMATE_FSM_AWAY,
        "sleeping": CLIMATE_FSM_SLEEPING,
        "party": CLIMATE_FSM_PARTY,
    }
    return fsm_map.get(mode, CLIMATE_FSM_DEFAULT)


def get_guard_function(guard_name: str):
    """Получить функцию guard по имени."""
    return GUARD_FUNCTIONS.get(guard_name)


def evaluate_guards(transitions: list, ctx: Dict[str, Any]) -> list:
    """
    Оценить все переходы и вернуть подходящие.
    
    Args:
        transitions: Список переходов из текущего состояния
        ctx: Контекст (температуры, флаги, таймеры)
    
    Returns:
        Список кортежей (priority, transition) отсортированных по приоритету
    """
    suitable = []
    
    for transition in transitions:
        guard_name = transition.get("guard")
        
        if guard_name is None:
            # Переход без guard всегда доступен
            suitable.append((transition.get("priority", 0), transition))
            continue
        
        guard_func = get_guard_function(guard_name)
        if guard_func and guard_func(ctx):
            suitable.append((transition.get("priority", 0), transition))
    
    # Сортировка по приоритету (убывание)
    suitable.sort(key=lambda x: x[0], reverse=True)
    return suitable


def build_context(
    zone_id: str,
    current_temp: float,
    target_temp: float,
    hvac_mode: str = "auto",
    manual_mode: bool = False,
    override_remaining_min: int = 0,
    sensor_error: bool = False,
    heating_lockout: bool = False,
    lockout_timer_expired: bool = True,
    room_context: str = "HOME_DAY",
    target_temp_away: float = 18.0,
    target_temp_sleep: float = 20.0,
    target_temp_party: float = 22.0,
) -> Dict[str, Any]:
    """
    Построить контекст для оценки guards.
    
    Args:
        zone_id: Идентификатор зоны
        current_temp: Текущая температура
        target_temp: Целевая температура
        hvac_mode: Режим HVAC (heat, cool, auto)
        manual_mode: Активен ли ручной режим
        override_remaining_min: Осталось минут ручного управления
        sensor_error: Ошибка датчика
        heating_lockout: Глобальная блокировка отопления
        lockout_timer_expired: Истек ли таймер блокировки
        room_context: Контекст комнаты (EMPTY, HOME_DAY, SLEEPING, PARTY)
        target_temp_away: Целевая температура для режима Away
        target_temp_sleep: Целевая температура для режима Sleeping
        target_temp_party: Целевая температура для режима Party
    
    Returns:
        Словарь контекста для FSM
    """
    return {
        "zone_id": zone_id,
        "current_temperature": current_temp,
        "target_temperature": target_temp,
        "hvac_mode": hvac_mode,
        "manual_mode": manual_mode,
        "override_remaining_min": override_remaining_min,
        "sensor_error": sensor_error,
        "heating_lockout": heating_lockout,
        "lockout_timer_expired": lockout_timer_expired,
        "room_context": room_context,
        "target_temperature_away": target_temp_away,
        "target_temperature_sleep": target_temp_sleep,
        "target_temperature_party": target_temp_party,
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
        return f"[climate][{zone_id}] {description}: {reason}"
    return f"[climate][{zone_id}] {description}"
