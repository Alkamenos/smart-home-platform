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
    _fsm_ensure_restored(entity_id)
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


import time

_FSM_LAST_TRANSITION = {}
_DEBOUNCE_EXEMPT_DEFAULT = {"manual_change", "manual_override", "critical_co2",
                            "timeout_expired", "override_expired"}


def fsm_trigger(entity_id, trigger, src="автоматика", ctx=None):
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

    _fsm_ensure_restored(entity_id)
    current_state = fsm_get_state(entity_id)
    transitions = definition.get("transitions", [])
    
    # Получаем предыдущее состояние из истории для поддержки PREVIOUS
    previous_state = None
    entry = _FSM_STATES.get(entity_id)
    if entry and entry.get("history"):
        last_transition = entry["history"][0]
        prev = last_transition.get("from")
        if prev and prev in definition.get("states", []):
            previous_state = prev

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
            guard = t.get("guard")
            if guard and ctx is not None:
                try:
                    # Безопасное выполнение guard-выражения из контекста
                    if not eval(guard, {"__builtins__": {}}, ctx):
                        continue
                except Exception:
                    continue
            candidates.append(t)

    if not candidates:
        return False

    # Сортируем по приоритету (убывание) и берём лучший
    candidates.sort(key=lambda t: t.get("priority", 0), reverse=True)
    best = candidates[0]

    target_state = best.get("to")
    
    # Обработка псевдонима PREVIOUS
    if target_state == "PREVIOUS":
        if previous_state:
            target_state = previous_state
        else:
            target_state = definition.get("initial", "OFF")
    
    why = best.get("why", "")

    # Проверяем, что целевое состояние существует и отличается от текущего
    if target_state not in definition.get("states", []):
        return False
    if target_state == current_state:
        return False

    # Debounce: кулдаун на переходы (кроме ручных/критических триггеров)
    now = time.monotonic()
    cooldown = float(definition.get("debounce_sec", 0) or 0)
    exempt = definition.get("debounce_exempt") or _DEBOUNCE_EXEMPT_DEFAULT
    if cooldown > 0 and trigger not in exempt:
        last = _FSM_LAST_TRANSITION.get(entity_id)
        if last is not None and now - last < cooldown:
            return False

    # Выполняем переход
    _FSM_LAST_TRANSITION[entity_id] = now
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

    # Debounced сохранение (1 сек)
    try:
        task.unique("fsm_save", kill_me=True)
        task.sleep(1)
        fsm_save_states()
    except Exception:
        pass


_FSM_RESTORED = set()


def _fsm_ensure_restored(entity_id):
    """Восстановить состояние из persist, если ещё не загружено."""
    if entity_id in _FSM_RESTORED:
        return
    _FSM_RESTORED.add(entity_id)
    if entity_id not in _FSM_STATES:
        try:
            fsm_load_states()
        except Exception:
            pass


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


def _fsm_publish_overview():
    """Публикует агрегированное состояние всех автоматов в сенсор."""
    try:
        overview = {}
        for entity_id, entry in _FSM_STATES.items():
            overview[entity_id] = entry.get("state", "UNKNOWN")

        # Публикуем в сенсор
        state.set("sensor.fsm_overview", str(len(overview)),
                  count=str(len(overview)),
                  states=str(overview),
                  updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass


def fsm_publish_all():
    """Принудительная публикация состояний всех автоматов."""
    for entity_id in _FSM_STATES:
        _fsm_publish_state(entity_id)
    _fsm_publish_overview()
    return {"ok": True, "count": len(_FSM_STATES)}


# ==================== ПЕРСИСТ СОСТОЯНИЙ ====================

_FSM_PERSIST_PATH = "/config/.fsm_states.json"


def fsm_save_states():
    """Сохранить FSM-состояния в файл; в helper — короткая сводка."""
    try:
        import json
        data = {}
        for eid, entry in _FSM_STATES.items():
            data[eid] = {"state": entry.get("state")}
        with open(_FSM_PERSIST_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        try:
            service.call("input_text", "set_value", entity_id="input_text.fsm_persist",
                         value="saved %d states %s" % (len(data),
                               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        except Exception:
            pass
    except Exception as exc:
        log.error("[fsm] save_states failed: " + str(exc))


def fsm_load_states():
    """Восстановить FSM-состояния из файла персиста."""
    try:
        import json
        with open(_FSM_PERSIST_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
        n = 0
        for eid, v in loaded.items():
            if eid in _FSM_STATES or not isinstance(v, dict) or not v.get("state"):
                continue
            _FSM_STATES[eid] = {"state": v["state"], "entered_at": "restored",
                                "entered_by": "persist", "entered_why": "восстановлено после рестарта",
                                "history": []}
            n += 1
        log.info("[fsm] restored %d states" % n)
    except Exception as exc:
        log.error("[fsm] load_states failed: " + str(exc))


def fsm_sync_with_device(entity_id, device_state_mapper):
    """
    Синхронизирует FSM состояние с реальным состоянием устройства.
    
    Args:
        entity_id: идентификатор сущности (например, "cover.bedroom")
        device_state_mapper: функция, которая возвращает текущее состояние устройства
                           и маппинг реального состояния в FSM состояние
    
    Пример использования:
        fsm_sync_with_device("cover.bedroom", 
                            lambda: (_cv_get_actual_position("cover.bedroom"), 
                                    {>=80: "OPEN", <=20: "CLOSED", else: "PARTIAL"}))
    """
    _fsm_ensure_restored(entity_id)
    definition = _FSM_DEFINITIONS.get(entity_id)
    if definition is None:
        return False
    
    current_fsm_state = fsm_get_state(entity_id)
    device_value, state_map = device_state_mapper()
    
    if device_value is None:
        return False
    
    # Определяем ожидаемое FSM состояние на основе реального состояния устройства
    expected_state = None
    for threshold, fsm_state in state_map.items():
        if isinstance(threshold, tuple):
            # Диапазон (min, max)
            if threshold[0] <= device_value <= threshold[1]:
                expected_state = fsm_state
                break
        elif callable(threshold):
            # Функция-предикат
            if threshold(device_value):
                expected_state = fsm_state
                break
        else:
            # Точное значение
            if device_value == threshold:
                expected_state = fsm_state
                break
    
    if expected_state is None or expected_state == current_fsm_state:
        return False
    
    # Проверяем, не в MANUAL_LOCK ли мы
    if current_fsm_state == "MANUAL_LOCK":
        # Не синхронизируем если есть ручная блокировка
        entry = _FSM_STATES.get(entity_id)
        if entry:
            debounce_sec = float(definition.get("debounce_sec", 0) or 0)
            entered_at = entry.get("entered_at")
            if entered_at:
                try:
                    from datetime import datetime
                    entered_dt = datetime.strptime(entered_at, "%Y-%m-%d %H:%M:%S")
                    if (datetime.now() - entered_dt).total_seconds() < 300:  # 5 минут
                        return False  # Ещё не истёк таймаут
                except Exception:
                    pass
    
    # Синхронизируем через соответствующий триггер
    sync_trigger = None
    if "OPEN" in str(state_map.values()):
        sync_trigger = "sync_open"
    if "CLOSED" in str(state_map.values()):
        sync_trigger = "sync_close"
    if "PARTIAL" in str(state_map.values()):
        sync_trigger = "sync_partial"
    
    if sync_trigger:
        # Проверяем существует ли такой триггер в определениях
        transitions = definition.get("transitions", [])
        valid_sync = any(t.get("trigger") == sync_trigger for t in transitions)
        if valid_sync:
            fsm_trigger(entity_id, sync_trigger, src="watchdog_sync")
            return True
    
    return False

def fsm_get_all_states():
    """Возвращает словарь всех зарегистрированных FSM состояний."""
    return dict(_FSM_STATES)

def fsm_force_state(entity_id, new_state, why="Принудительная синхронизация"):
    """
    Принудительно устанавливает состояние FSM (для отладки и аварийных случаев).
    
    Args:
        entity_id: идентификатор сущности
        new_state: новое состояние
        why: причина изменения
    """
    _fsm_ensure_restored(entity_id)
    if entity_id not in _FSM_DEFINITIONS:
        return False
    
    definition = _FSM_DEFINITIONS[entity_id]
    if new_state not in definition.get("states", []):
        return False
    
    _fsm_set_state(entity_id, new_state, "force", why, src="watchdog")
    return True

# ==================== GENERIC WATCHDOG: FSM vs device ====================
# Фича регистрирует маппер (устройство -> ожидаемое FSM-состояние);
# watchdog чинит расхождение, если оно держится дольше grace_sec.

_FSM_SYNC_MAPPERS = {}

def fsm_register_sync(entity_id, mapper, grace_sec=120):
    """Регистрация маппера реального состояния для watchdog. mapper() -> ожидаемое FSM-состояние или None."""
    _FSM_SYNC_MAPPERS[entity_id] = {"mapper": mapper, "grace": float(grace_sec), "diverged_at": None}

def fsm_sync_tick():
    """Один проход сверки FSM vs устройство по всем зарегистрированным мапперам."""
    now = time.monotonic()
    for entity_id, info in list(_FSM_SYNC_MAPPERS.items()):
        try:
            expected = info["mapper"]()
        except Exception:
            expected = None
        current = fsm_get_state(entity_id)
        if expected is None or current is None or expected == current or current == "MANUAL_LOCK":
            info["diverged_at"] = None
            continue
        if info["diverged_at"] is None:
            info["diverged_at"] = now
            continue
        if now - info["diverged_at"] < info["grace"]:
            continue
        definition = _FSM_DEFINITIONS.get(entity_id) or {}
        trig_map = {"OPEN": "sync_open", "CLOSED": "sync_close", "PARTIAL": "sync_partial"}
        trig = trig_map.get(expected)
        synced = False
        if trig and any(t.get("trigger") == trig for t in definition.get("transitions", [])):
            synced = fsm_trigger(entity_id, trig, src="watchdog")
        if not synced and expected in (definition.get("states") or []):
            _fsm_set_state(entity_id, expected, "watchdog_sync",
                           "Watchdog: расхождение с устройством", "watchdog")
            synced = True
        if synced:
            log.info("[fsm] watchdog sync: %s -> %s" % (entity_id, expected))
        info["diverged_at"] = None

try:
    time_trigger
    _FSM_PYSCRIPT = True
except NameError:
    _FSM_PYSCRIPT = False

if _FSM_PYSCRIPT:
    @time_trigger("startup")
    def _fsm_sync_watchdog_loop():
        while True:
            try:
                fsm_sync_tick()
            except Exception as exc:
                log.error("[fsm] sync watchdog error: " + str(exc))
            task.sleep(60)
