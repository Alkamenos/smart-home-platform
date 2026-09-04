# ============================================================
# FSM: Автомат штор
# Описание состояний и переходов для фичи "Шторы"
# ============================================================

# Автомат по умолчанию для обычных штор
COVER_FSM_DEFAULT = {
    "states": ["OPEN", "CLOSED", "PARTIAL", "MANUAL_LOCK", "ERROR"],
    "initial": "CLOSED",
    "transitions": [
        # Расписание: открытие днём
        {
            "from": ["CLOSED"],
            "to": "OPEN",
            "trigger": "schedule_day",
            "priority": 20,
            "why": "Открытие по расписанию (день)"
        },
        # Расписание: закрытие ночью
        {
            "from": ["OPEN"],
            "to": "CLOSED",
            "trigger": "schedule_night",
            "priority": 20,
            "why": "Закрытие по расписанию (ночь)"
        },
        # Частичное закрытие при определённых условиях
        {
            "from": ["OPEN", "CLOSED"],
            "to": "PARTIAL",
            "trigger": "partial_adjust",
            "priority": 15,
            "why": "Частичная регулировка положения"
        },
        # Возврат из PARTIAL в OPEN
        {
            "from": ["PARTIAL"],
            "to": "OPEN",
            "trigger": "schedule_day",
            "priority": 20,
            "why": "Возврат в открытое состояние"
        },
        # Возврат из PARTIAL в CLOSED
        {
            "from": ["PARTIAL"],
            "to": "CLOSED",
            "trigger": "schedule_night",
            "priority": 20,
            "why": "Возврат в закрытое состояние"
        },
        # Уход: закрытие
        {
            "from": ["OPEN", "PARTIAL"],
            "to": "CLOSED",
            "trigger": "presence_leave",
            "priority": 30,
            "why": "Закрытие при уходе из дома"
        },
        # Приход: открытие
        {
            "from": ["CLOSED", "PARTIAL"],
            "to": "OPEN",
            "trigger": "presence_arrive",
            "priority": 30,
            "why": "Открытие при приходе домой"
        },
        # Ручное вмешательство: блокировка автоматики
        {
            "from": ["OPEN", "CLOSED", "PARTIAL"],
            "to": "MANUAL_LOCK",
            "trigger": "manual_change",
            "priority": 100,
            "why": "Ручное вмешательство — автоматика заблокирована"
        },
        # Таймер блокировки истёк: возврат к автоматике
        {
            "from": "MANUAL_LOCK",
            "to": "CLOSED",
            "trigger": "timeout",
            "priority": 10,
            "why": "Таймер блокировки истёк — возврат к автоматике"
        },
        # Явный сброс блокировки
        {
            "from": "MANUAL_LOCK",
            "to": "OPEN",
            "trigger": "override_clear",
            "priority": 50,
            "why": "Явный сброс блокировки"
        },
        # Аварийное открытие (пожар, протечка)
        {
            "from": "*",
            "to": "OPEN",
            "trigger": "emergency",
            "priority": 1000,
            "why": "Аварийное открытие"
        },
        # Ошибка привода
        {
            "from": "*",
            "to": "ERROR",
            "trigger": "device_error",
            "priority": 500,
            "why": "Ошибка привода"
        },
        # Синхронизация с реальной позицией при старте
        {
            "from": ["CLOSED", "PARTIAL"],
            "to": "OPEN",
            "trigger": "sync_open",
            "priority": 1,
            "why": "Синхронизация: штора открыта"
        },
        {
            "from": ["OPEN", "PARTIAL"],
            "to": "CLOSED",
            "trigger": "sync_close",
            "priority": 1,
            "why": "Синхронизация: штора закрыта"
        },
        {
            "from": ["OPEN", "CLOSED"],
            "to": "PARTIAL",
            "trigger": "sync_partial",
            "priority": 1,
            "why": "Синхронизация: штора частично открыта"
        }
    ]
}

# Автомат для шторы над дверью (с учётом пожарной безопасности)
COVER_FSM_DOOR = {
    "states": ["OPEN", "CLOSED", "PARTIAL", "MANUAL_LOCK", "ERROR"],
    "initial": "CLOSED",
    "transitions": [
        # Расписание: открытие днём
        {
            "from": ["CLOSED", "PARTIAL"],
            "to": "OPEN",
            "trigger": "schedule_day",
            "priority": 20,
            "why": "Открытие по расписанию (день)"
        },
        # Расписание: частичное закрытие ночью (пожарная безопасность)
        {
            "from": ["OPEN", "PARTIAL"],
            "to": "PARTIAL",
            "trigger": "schedule_night",
            "priority": 20,
            "why": "Частичное закрытие ночью (пожарная безопасность)"
        },
        # Уход: частичное закрытие (пожарная безопасность)
        {
            "from": ["OPEN", "PARTIAL"],
            "to": "PARTIAL",
            "trigger": "presence_leave",
            "priority": 30,
            "why": "Частичное закрытие при уходе (пожарная безопасность)"
        },
        # Приход: открытие
        {
            "from": ["CLOSED", "PARTIAL"],
            "to": "OPEN",
            "trigger": "presence_arrive",
            "priority": 30,
            "why": "Открытие при приходе домой"
        },
        # Ручное вмешательство: блокировка автоматики
        {
            "from": ["OPEN", "CLOSED", "PARTIAL"],
            "to": "MANUAL_LOCK",
            "trigger": "manual_change",
            "priority": 100,
            "why": "Ручное вмешательство — автоматика заблокирована"
        },
        # Таймер блокировки истёк: возврат к автоматике
        {
            "from": "MANUAL_LOCK",
            "to": "PARTIAL",
            "trigger": "timeout",
            "priority": 10,
            "why": "Таймер блокировки истёк — возврат к автоматике"
        },
        # Явный сброс блокировки
        {
            "from": "MANUAL_LOCK",
            "to": "OPEN",
            "trigger": "override_clear",
            "priority": 50,
            "why": "Явный сброс блокировки"
        },
        # Аварийное открытие (пожар)
        {
            "from": "*",
            "to": "OPEN",
            "trigger": "emergency",
            "priority": 1000,
            "why": "Аварийное открытие (пожарная безопасность)"
        },
        # Ошибка привода
        {
            "from": "*",
            "to": "ERROR",
            "trigger": "device_error",
            "priority": 500,
            "why": "Ошибка привода"
        },
        # Синхронизация с реальной позицией при старте
        {
            "from": ["CLOSED", "PARTIAL"],
            "to": "OPEN",
            "trigger": "sync_open",
            "priority": 1,
            "why": "Синхронизация: штора открыта"
        },
        {
            "from": ["OPEN", "PARTIAL"],
            "to": "CLOSED",
            "trigger": "sync_close",
            "priority": 1,
            "why": "Синхронизация: штора закрыта"
        },
        {
            "from": ["OPEN", "CLOSED"],
            "to": "PARTIAL",
            "trigger": "sync_partial",
            "priority": 1,
            "why": "Синхронизация: штора частично открыта"
        }
    ]
}


def cover_fsm_definition(c):
    """Возвращает определение автомата для конкретной шторы.

    Args:
        c: словарь конфигурации шторы из манифеста

    Returns:
        определение автомата (COVER_FSM_DEFAULT или COVER_FSM_DOOR)
    """
    if c.get("door"):
        return COVER_FSM_DOOR
    return COVER_FSM_DEFAULT
