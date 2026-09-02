# ============================================================
# RUNTIME: Контроллер автомата комнаты
# Слушает изменения присутствия и времени суток,
# триггерит переходы автомата комнаты.
# Префикс _room_ для избежания коллизий.
# ============================================================

from datetime import datetime

# Флаг инициализации
_ROOM_INITIALIZED = False


def _room_is_night():
    """Определяет, сейчас ночь или день.
    Использует состояние sun.sun (above_horizon / below_horizon).
    """
    sun_state = _cv_state("sun.sun")
    if sun_state == "below_horizon":
        return True
    # Fallback: проверяем хелпер vecher
    vecher = _cv_state("input_boolean.vecher")
    return vecher == "on"


def _room_init():
    """Инициализация автомата комнаты."""
    global _ROOM_INITIALIZED
    if _ROOM_INITIALIZED:
        return

    definition = room_fsm_definition("main")
    fsm_register("room.main", definition)

    # Определяем начальное состояние на основе текущего контекста
    my_doma = _cv_state("input_boolean.my_doma")
    party = _cv_state("input_boolean.party_mode")
    is_night = _room_is_night()

    if party == "on":
        initial = "PARTY"
    elif my_doma != "on":
        initial = "EMPTY"
    elif is_night:
        initial = "HOME_NIGHT"
    else:
        initial = "HOME_DAY"

    # Если начальное состояние отличается от стандартного — форсируем
    if initial != definition.get("initial"):
        _FSM_STATES["room.main"]["state"] = initial
        _FSM_STATES["room.main"]["entered_by"] = "init"
        _FSM_STATES["room.main"]["entered_why"] = "Определение начального состояния при старте"
        _fsm_publish_state("room.main")

    _ROOM_INITIALIZED = True
    log.info("[room] FSM initialized: state=" + initial)


def _room_trigger_presence():
    """Обработка изменения присутствия."""
    my_doma = _cv_state("input_boolean.my_doma")
    current = fsm_get_state("room.main")

    if my_doma == "on":
        # Пришли домой
        if current == "EMPTY":
            is_night = _room_is_night()
            if is_night:
                fsm_trigger("room.main", "presence_arrive_night", src="присутствие")
            else:
                fsm_trigger("room.main", "presence_arrive_day", src="присутствие")
    else:
        # Ушли из дома
        if current != "EMPTY":
            fsm_trigger("room.main", "presence_leave", src="присутствие")


def _room_trigger_party():
    """Обработка изменения режима вечеринки."""
    party = _cv_state("input_boolean.party_mode")
    current = fsm_get_state("room.main")

    if party == "on" and current in ("HOME_DAY", "HOME_NIGHT"):
        fsm_trigger("room.main", "party_on", src="ручное")
    elif party != "on" and current == "PARTY":
        fsm_trigger("room.main", "party_off", src="ручное")


def _room_check_sun():
    """Проверяет закат/рассвет и триггерит переходы."""
    current = fsm_get_state("room.main")
    is_night = _room_is_night()

    if current == "HOME_DAY" and is_night:
        fsm_trigger("room.main", "sunset", src="таймер")
    elif current == "HOME_NIGHT" and not is_night:
        fsm_trigger("room.main", "sunrise", src="таймер")


# ──────────────────────────────────────────────────────────────
# Триггеры: слушаем изменения присутствия и вечеринки
# ──────────────────────────────────────────────────────────────


def _room_trigger_sleep():
    """Обработка изменения режима сна."""
    sleep = _cv_state("input_boolean.sleep_mode")
    current = fsm_get_state("room.main")
    is_night = _room_is_night()

    if sleep == "on" and current in ("HOME_DAY", "HOME_NIGHT", "PARTY"):
        fsm_trigger("room.main", "sleep_on", src="ручное")
    elif sleep != "on" and current == "SLEEPING":
        # Пробуждение: определяем, день сейчас или ночь
        if is_night:
            fsm_trigger("room.main", "sleep_off_night", src="ручное")
        else:
            fsm_trigger("room.main", "sleep_off", src="ручное")


@state_trigger("input_boolean.my_doma")
def _room_presence_handler(var_name=None, **kwargs):
    """Обработчик изменения присутствия."""
    if not _ROOM_INITIALIZED:
        return
    _room_trigger_presence()


@state_trigger("input_boolean.party_mode")
def _room_party_handler(var_name=None, **kwargs):
    """Обработчик изменения режима вечеринки."""
    if not _ROOM_INITIALIZED:
        return
    _room_trigger_party()



@state_trigger("input_boolean.sleep_mode")
def _room_sleep_handler(var_name=None, **kwargs):
    """Обработчик изменения режима сна."""
    if not _ROOM_INITIALIZED:
        return
    _room_trigger_sleep()


@state_trigger("sun.sun")
def _room_sun_handler(var_name=None, **kwargs):
    """Обработчик изменения положения солнца."""
    if not _ROOM_INITIALIZED:
        return
    _room_check_sun()


# ──────────────────────────────────────────────────────────────
# Главный цикл: проверка таймеров и периодическая синхронизация
# ──────────────────────────────────────────────────────────────

@time_trigger("startup")
def room_controller_loop():
    """Главный цикл контроллера комнаты."""
    log.info("[room] Controller loop started")

    # Инициализация
    _room_init()

    while True:
        try:
            # Периодическая проверка заката/рассвета (на случай если @state_trigger не сработал)
            _room_check_sun()

            # Публикуем контекст комнаты для других фич
            room_state = fsm_get_state("room.main")
            if room_state:
                try:
                    state.set("sensor.room_context", room_state,
                              fsm_state=room_state,
                              updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                except Exception:
                    pass

        except Exception as exc:
            log.error("[room] Controller error: " + str(exc))

        task.sleep(60)


# ──────────────────────────────────────────────────────────────
# Сервисы диагностики
# ──────────────────────────────────────────────────────────────

@service
def room_fsm_debug():
    """Диагностика автомата комнаты."""
    result = fsm_debug("room.main")
    for eid, info in result.items():
        if "error" in info:
            log.warning("[room][fsm_debug] " + str(eid) + ": " + str(info["error"]))
        else:
            log.warning("[room][fsm_debug] " + str(eid)
                        + " | state=" + str(info["state"])
                        + " | entered_at=" + str(info["entered_at"])
                        + " | entered_by=" + str(info["entered_by"])
                        + " | why=" + str(info["entered_why"]))
            for h in info.get("history", []):
                log.warning("[room][fsm_debug]   " + str(h["time"])
                            + " | " + str(h["from"]) + " → " + str(h["to"])
                            + " | trigger=" + str(h["trigger"])
                            + " | why=" + str(h["why"]))
    return {"ok": True, "fsm": result}


@service
def room_fsm_set(state_name):
    """Принудительная установка состояния комнаты (для отладки)."""
    valid_states = ["EMPTY", "HOME_DAY", "HOME_NIGHT", "PARTY", "SLEEPING"]
    if state_name not in valid_states:
        return {"ok": False, "error": "invalid state: " + str(state_name)}

    _FSM_STATES["room.main"]["state"] = state_name
    _FSM_STATES["room.main"]["entered_by"] = "manual_set"
    _FSM_STATES["room.main"]["entered_why"] = "Принудительная установка через сервис"
    _fsm_publish_state("room.main")
    log_event("platform", "Инфо", "Состояние комнаты установлено вручную: " + state_name, src="ручное")
    return {"ok": True, "state": state_name}
