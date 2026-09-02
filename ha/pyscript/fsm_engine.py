# ============================================================
# FSM ENGINE — Универсальный движок конечных автоматов
# Конкатенируется ПОСЛЕ registry.py, ПЕРЕД manifest_loader.py.
# Префикс _fsm_ для избежания коллизий.
# ============================================================

from datetime import datetime

# Глобальное хранилище состояний автоматов
_FSM_STATES = {}
# {entity_id: {
#   "state": str, "entered_at": str, "entered_by": str,
#   "entered_why": str, "history": [...]
# }}

# Глобальное хранилище определений автоматов
_FSM_DEFINITIONS = {}
# {entity_id: {
#   "states": [...], "initial": str, "transitions": [...]
# }}

# Максимальный размер истории переходов
_FSM_HISTORY_MAX = 20


def fsm_register(entity_id, definition):
    """Регистрация автомата для сущности.

    Args:
        entity_id: идентификатор сущности (например, "cover.bedroom")
        definition: словарь с описанием автомата:
            - states: список состояний
            - initial: начальное состояние
            - transitions: список переходов
    """
    _FSM_DEFINITIONS[entity_id] = definition

    # Инициализируем состояние, если ещё не было
    if entity_id not in _FSM_STATES:
        initial = definition.get("initial", "UNKNOWN")
        _FSM_STATES[entity_id] = {
            "state": initial,
            "entered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "entered_by": "init",
            "entered_why": "Инициализация при старте",
            "history": []
        }
        _fsm_publish_state(entity_id)


def fsm_get_state(entity_id):
    """Получить текущее состояние автомата."""
    entry = _FSM_STATES.get(entity_id)
    if entry is None:
        return None
    return entry.get("state")


def fsm_get_history(entity_id, limit=5):
    """Получить историю переходов."""
    entry = _FSM_STATES.get(entity_id)
    if entry is None:
        return []
    return entry.get("history", [])[:limit]


def fsm_trigger(entity_id, trigger, src="автоматика"):
    """Обработка триггера: найти переход, сменить состояние.

    При конфликте нескольких переходов побеждает наивысший приоритет.

    Args:
        entity_id: идентификатор сущности
        trigger: имя триггера (например, "manual_change")
        src: источник триггера (для логирования)

    Returns:
        True если переход произошёл, False иначе
    """
    definition = _FSM_DEFINITIONS.get(entity_id)
    if definition is None:
        return False

    current_state = fsm_get_state(entity_id)
    transitions = definition.get("transitions", [])

    # Находим все подходящие переходы
    candidates = []
    for t in transitions:
        if t.get("trigger") != trigger:
            continue

        from_states = t.get("from", [])
        if isinstance(from_states, str):
            from_states = [from_states]

        # Проверяем, подходит ли текущее состояние
        if "*" in from_states or current_state in from_states:
            candidates.append(t)

    if not candidates:
        return False

    # Сортируем по приоритету (убывание) и берём лучший
    candidates.sort(key=lambda t: t.get("priority", 0), reverse=True)
    best = candidates[0]

    target_state = best.get("to")
    why = best.get("why", "")

    # Проверяем, что целевое состояние существует и отличается от текущего
    if target_state not in definition.get("states", []):
        return False
    if target_state == current_state:
        return False

    # Выполняем переход
    _fsm_set_state(entity_id, target_state, trigger, why, src)
    return True


def _fsm_set_state(entity_id, new_state, trigger, why="", src="автоматика"):
    """Сменить состояние автомата (внутренняя функция)."""
    entry = _FSM_STATES.get(entity_id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if entry is None:
        entry = {
            "state": new_state,
            "entered_at": now_str,
            "entered_by": trigger,
            "entered_why": why,
            "history": []
        }
        _FSM_STATES[entity_id] = entry
    else:
        old_state = entry.get("state")

        # Добавляем в историю
        history_entry = {
            "time": now_str,
            "from": old_state,
            "to": new_state,
            "trigger": trigger,
            "why": why,
            "src": src
        }
        entry["history"].insert(0, history_entry)

        # Обрезаем историю
        if len(entry["history"]) > _FSM_HISTORY_MAX:
            entry["history"] = entry["history"][:_FSM_HISTORY_MAX]

        # Обновляем состояние
        entry["state"] = new_state
        entry["entered_at"] = now_str
        entry["entered_by"] = trigger
        entry["entered_why"] = why

    # Публикуем состояние в сенсор
    _fsm_publish_state(entity_id)

    # Логируем переход
    _fsm_log_transition(entity_id, new_state, trigger, why, src)


def _fsm_publish_state(entity_id):
    """Публикуем состояние автомата в sensor."""
    entry = _FSM_STATES.get(entity_id)
    if entry is None:
        return

    sensor_name = "sensor." + entity_id.replace(".", "_") + "_fsm_state"
    try:
        state.set(sensor_name, entry["state"],
                  entered_at=entry["entered_at"],
                  entered_by=entry["entered_by"],
                  entered_why=entry["entered_why"],
                  history_count=str(len(entry["history"])))
    except Exception:
        pass


def _fsm_log_transition(entity_id, new_state, trigger, why, src):
    """Логируем переход через log_event."""
    try:
        entry = _FSM_STATES.get(entity_id)
        history = entry.get("history", []) if entry else []

        if history:
            last = history[0]
            msg = "%s: %s → %s" % (entity_id, last["from"], last["to"])
        else:
            msg = "%s: → %s" % (entity_id, new_state)

        # Определяем домен по типу сущности
        domain = entity_id.split(".")[0] if "." in entity_id else "platform"
        domain_map = {
            "cover": "covers",
            "light": "lighting",
            "climate": "climate",
            "fan": "ventilation"
        }
        log_domain = domain_map.get(domain, domain)

        log_event(log_domain, "Инфо", msg, why=why, src=src)
    except NameError:
        # log_event ещё не определён (загрузка модулей)
        pass
    except Exception:
        pass


def fsm_debug(entity_id=None):
    """Диагностика автоматов. Вызывается через сервис."""
    result = {}

    targets = [entity_id] if entity_id else list(_FSM_STATES.keys())

    for eid in targets:
        entry = _FSM_STATES.get(eid)
        definition = _FSM_DEFINITIONS.get(eid)

        if entry is None:
            result[eid] = {"error": "not registered"}
            continue

        result[eid] = {
            "state": entry["state"],
            "entered_at": entry["entered_at"],
            "entered_by": entry["entered_by"],
            "entered_why": entry["entered_why"],
            "history": entry["history"][:5],
            "states": definition.get("states", []) if definition else [],
            "transitions_count": len(definition.get("transitions", [])) if definition else 0
        }

    return result
