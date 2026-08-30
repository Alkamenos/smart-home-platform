# pyscript runtime: covers controller (склейка через build/build_pyscript.py)
# Порядок: после lighting_controller.py. Все ссылки — call-time.
# Префикс _cv_ для избежания коллизий с _lg_/_clim_ и т.д.

import time

_CV_PREV = {}
_CV_OVERRIDE = {}
_CV_LAST_CHANGE = {}
_CV_EXPECTED_STATE = {}

# Глобальная настройка логирования
_CV_LOG_LEVELS = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3, "DEBUG": 4}
_CV_LOG_LEVEL = _CV_LOG_LEVELS.get("INFO", 3)
_CV_MODULE_LOG_LEVELS = {}


def _cv_get_log_level():
    """Получить уровень логирования из манифеста"""
    global _CV_LOG_LEVEL, _CV_MODULE_LOG_LEVELS
    if _REGISTRY is None:
        return
    cfg = _REGISTRY.feature("logging") or {}
    level_name = cfg.get("level", "INFO")
    _CV_LOG_LEVEL = _CV_LOG_LEVELS.get(level_name, 3)
    modules = cfg.get("modules", {})
    for mod, lvl in modules.items():
        _CV_MODULE_LOG_LEVELS[mod] = _CV_LOG_LEVELS.get(lvl, 3)


def _cv_log(module, level_name, msg):
    """Логирование с проверкой уровня"""
    level_val = _CV_LOG_LEVELS.get(level_name, 3)
    module_level = _CV_MODULE_LOG_LEVELS.get(module, _CV_LOG_LEVEL)
    if level_val <= module_level:
        if level_name == "DEBUG":
            log.info("[covers][DEBUG][" + module + "] " + msg)
        elif level_name == "INFO":
            log.info("[covers][" + module + "] " + msg)
        else:
            log.warning("[covers][" + module + "] " + msg)


# ---------------- безопасное чтение состояний ----------------

def _cv_state(entity):
    """Безопасное чтение состояния сущности."""
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.state


def _cv_attr(entity, name):
    """Безопасное чтение атрибута сущности."""
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.attributes.get(name)


def _cv_now_min():
    """Текущее время в минутах от начала суток."""
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def _cv_hm(s):
    """Парсинг времени HH:MM в минуты."""
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _cv_dt_min(entity):
    """Чтение времени из input_datetime."""
    s = _cv_state(entity)
    if not s:
        return None
    try:
        parts = str(s).split(" ")
        t = parts[1] if len(parts) > 1 else parts[0]
        return _cv_hm(t[:5])
    except Exception:
        return None


def _cv_num(entity, default):
    """Чтение числа из input_number."""
    s = _cv_state(entity)
    if s is None:
        return default
    try:
        return float(s)
    except Exception:
        return default


def _cv_cfg():
    """Получение конфигурации фичи covers."""
    if _REGISTRY is None:
        return None
    _cv_get_log_level()
    cfg = _REGISTRY.feature("covers") or None
    if not cfg:
        return None
    out = dict(cfg)
    return out


def _cv_mode(cfg):
    """Определение режима работы (real/shadow)."""
    sh = _cv_state("input_boolean.covers_shadow_mode")
    if sh == "on":
        return "shadow"
    if sh == "off":
        return "real"
    return cfg.get("mode", "real")


def _cv_is_time_window_open(now_min, open_min, close_min):
    """
    Проверка: сейчас окно 'открыто' (день)?
    Окно открытости: от open_time до close_time с переходом через полночь.
    Пример: 08:00-00:00 -> день 08:00-00:00, ночь 00:00-08:00.
    """
    if open_min is None or close_min is None:
        return True  # по умолчанию считаем днём
    
    if open_min < close_min:
        # Обычный случай: 08:00-20:00
        return open_min <= now_min < close_min
    elif open_min > close_min:
        # Переход через полночь: 08:00-00:00
        return now_min >= open_min or now_min < close_min
    else:
        # open == close: считаем всегда закрытым или всегда открытым
        return False


def _cv_decide_cover(c, cfg, home, dogs):
    """
    Решение для одной шторы: вернуть желаемое состояние.
    Возвращает: {"action": "open" | "close" | "close_pct", "pct": N, "why": "..."}
    
    home = нас дома (my_doma == on)
    dogs = собаки дома (dogs_home == on)
    away = не home
    """
    cid = str(c.get("id"))
    cover_entity = c.get("cover")
    is_door = c.get("door", False)
    away_pct = c.get("away_closed_pct", 60) if is_door else 100
    
    # Читаем настройки из helpers
    auto_flag = _cv_state("input_boolean.cover_%s_auto" % cid)
    if auto_flag != "on":
        return None  # автоматика отключена для этой шторы
    
    # Режим открытия/закрытия
    close_sel = _cv_state("input_select.cover_%s_close" % cid)
    open_sel = _cv_state("input_select.cover_%s_open" % cid)
    
    # Время из helpers или дефолт
    defaults = cfg.get("defaults", {"open_time": "08:00", "close_time": "00:00"})
    open_min_helper = _cv_dt_min("input_datetime.cover_%s_open_time" % cid)
    if open_min_helper is None:
        open_min_helper = _cv_hm(defaults.get("open_time", "08:00"))
    
    close_min_helper = _cv_dt_min("input_datetime.cover_%s_close_time" % cid)
    if close_min_helper is None:
        close_min_helper = _cv_hm(defaults.get("close_time", "00:00"))
    
    now_min = _cv_now_min()
    
    # Определяем окно "открыто" (день)
    is_day_window = _cv_is_time_window_open(now_min, open_min_helper, close_min_helper)
    
    # Учитываем select'ы "Не открывать"/"Не закрывать"
    allow_open = (open_sel != "Не открывать")
    allow_close = (close_sel != "Не закрывать")
    
    # === ЛОГИКА ДЛЯ ОБЫЧНОЙ ШТОРЫ ===
    if not is_door:
        # ЗАКРЫТА если (сейчас окно "закрыто") ИЛИ (away И не dogs)
        # иначе ОТКРЫТА
        
        is_night = not is_day_window  # сейчас окно "закрыто" (ночь)
        away = not home
        
        should_be_closed = False
        why_parts = []
        
        if is_night and allow_close:
            should_be_closed = True
            why_parts.append("ночь/окно закрыто")
        elif away and not dogs:
            should_be_closed = True
            why_parts.append("пустой дом (нет нас и собак)")
        
        if should_be_closed:
            return {"action": "close", "pct": 0, "why": "; ".join(why_parts)}
        else:
            # Днём и (дома ИЛИ собаки) -> открывать
            if allow_open and is_day_window:
                return {"action": "open", "pct": 100, "why": "день + (дома или собаки)"}
            elif not allow_open:
                return {"action": "keep", "pct": None, "why": "Не открывать в настройках"}
            else:
                return {"action": "open", "pct": 100, "why": "по расписанию день"}
    
    # === ЛОГИКА ДЛЯ ШТОРЫ НАД ДВЕРЬЮ ===
    else:
        # ОТКРЫТА если (окно "открыто") И (home ИЛИ dogs)
        # ЗАКРЫТА НА 100% если (окно "закрыто") И home
        # ЗАКРЫТА НА away_closed_pct когда нас нет дома (и с собаками, и без)
        
        away = not home
        
        if is_day_window and (home or dogs):
            # День и (дома или собаки) -> полностью открыта
            return {"action": "open", "pct": 100, "why": "день + (дома или собаки), дверь"}
        elif is_day_window and away:
            # День но никого нет -> закрываем на away_pct (никогда не 100%)
            # position = 100 - away_closed_pct
            pos = 100 - away_pct
            return {"action": "close_pct", "pct": pos, "why": "день, пустой дом, дверь -> " + str(away_pct) + "%"}
        elif not is_day_window and home:
            # Ночь и дома -> закрываем полностью
            return {"action": "close", "pct": 0, "why": "ночь, дома, дверь -> 100%"}
        elif not is_day_window and away:
            # Ночь и никого нет -> закрываем на away_pct
            pos = 100 - away_pct
            return {"action": "close_pct", "pct": pos, "why": "ночь, пустой дом, дверь -> " + str(away_pct) + "%"}
        
        return {"action": "keep", "pct": None, "why": "нет решения для двери"}


def _cv_get_actual_position(cover_entity):
    """Получение фактического положения шторы."""
    pos = _cv_attr(cover_entity, "current_position")
    if pos is None:
        return None
    try:
        return int(pos)
    except Exception:
        return None


def _cv_set_cover_position(cover_entity, position, mode):
    """Установка положения шторы."""
    if position is None:
        return
    
    if mode == "shadow":
        log.warning("[covers][SHADOW] " + cover_entity + " -> position " + str(position))
    else:
        # Платформа помечает команду как ожидаемую
        _CV_EXPECTED_STATE[cover_entity] = {
            "position": position,
            "until": time.monotonic() + 30
        }
        service.call("cover", "set_cover_position", entity_id=cover_entity, position=position)
        log.warning("[covers][REAL] " + cover_entity + " -> position " + str(position))


def _cv_open_cover(cover_entity, mode):
    """Полное открытие шторы."""
    _cv_set_cover_position(cover_entity, 100, mode)


def _cv_close_cover(cover_entity, mode):
    """Полное закрытие шторы."""
    _cv_set_cover_position(cover_entity, 0, mode)


def _cv_override_active(cover_entity, timeout_min=60):
    """Проверка: есть ли активный override (ручное вмешательство)."""
    until = _CV_OVERRIDE.get(cover_entity)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _CV_OVERRIDE[cover_entity]
        return False
    return True


def _cv_expected_guard(cover_entity):
    """Проверка: ждём ли мы подтверждения команды."""
    exp = _CV_EXPECTED_STATE.get(cover_entity)
    if exp is None:
        return None
    if time.monotonic() > exp["until"]:
        _CV_EXPECTED_STATE.pop(cover_entity, None)
        return None
    return exp["position"]


def _cv_anti_cycle_ok(cover_entity, min_minutes=2):
    """Проверка анти-цикла: не слать команды чаще ~2 мин."""
    last = _CV_LAST_CHANGE.get(cover_entity, 0)
    return (time.monotonic() - last) >= (min_minutes * 60)


def _cv_track_manual_change(c, cfg):
    """Отслеживание ручного вмешательства."""
    cid = str(c.get("id"))
    cover_entity = c.get("cover")
    
    cur_pos = _cv_get_actual_position(cover_entity)
    if cur_pos is None:
        return
    
    prev_pos = _CV_PREV.get(cover_entity)
    _CV_PREV[cover_entity] = cur_pos
    
    if prev_pos is None or cur_pos == prev_pos:
        return
    
    # Проверяем, не наша ли это команда
    exp = _cv_expected_guard(cover_entity)
    if exp is not None:
        if abs(exp - cur_pos) < 5:  # допуск 5%
            _CV_EXPECTED_STATE.pop(cover_entity, None)
            return
    
    # Это ручное вмешательство — ставим override
    timeout = cfg.get("override_timeout_min", 60)
    _CV_OVERRIDE[cover_entity] = time.monotonic() + (timeout * 60)
    _cv_log("manual", "INFO", cover_entity + ": manual change detected, override " + str(timeout) + " min")


def _cv_apply_cover(c, cfg, mode, home, dogs):
    """Применение решения к шторе."""
    cid = str(c.get("id"))
    cover_entity = c.get("cover")
    
    # Сначала отслеживаем ручное вмешательство
    _cv_track_manual_change(c, cfg)
    
    # Проверяем override
    if _cv_override_active(cover_entity):
        return
    
    # Проверяем глобальный флаг
    feature_flag = _cv_state("input_boolean.feature_covers")
    if feature_flag != "on":
        return
    
    # Получаем решение
    dec = _cv_decide_cover(c, cfg, home, dogs)
    if dec is None:
        return  # автоматика отключена для этой шторы
    
    action = dec.get("action")
    if action == "keep":
        return
    
    # Проверяем анти-цикл
    if not _cv_anti_cycle_ok(cover_entity, cfg.get("anti_cycle_min", 2)):
        return
    
    # Применяем действие
    cur_pos = _cv_get_actual_position(cover_entity)
    target_pos = dec.get("pct")
    
    if target_pos is not None and cur_pos is not None:
        if abs(cur_pos - target_pos) < 5:  # допуск 5%
            return  # уже в нужном положении
    
    if action == "open":
        _cv_open_cover(cover_entity, mode)
    elif action == "close":
        _cv_close_cover(cover_entity, mode)
    elif action == "close_pct":
        _cv_set_cover_position(cover_entity, target_pos, mode)
    
    _cv_log("apply", "INFO", cid + ": " + dec.get("why", ""))
    _CV_LAST_CHANGE[cover_entity] = time.monotonic()


def _cv_immediate_close_on_leave(cfg, covers_list):
    """Немедленное закрытие всех штор при уходе (my_doma -> off)."""
    mode = _cv_mode(cfg)
    home = False
    dogs = _cv_state("input_boolean.dogs_home") == "on"
    
    for c in covers_list:
        cid = str(c.get("id"))
        auto_flag = _cv_state("input_boolean.cover_%s_auto" % cid)
        if auto_flag != "on":
            continue
        
        cover_entity = c.get("cover")
        is_door = c.get("door", False)
        away_pct = c.get("away_closed_pct", 60) if is_door else 100
        
        # Проверяем override
        if _cv_override_active(cover_entity):
            continue
        
        # Проверяем анти-цикл
        if not _cv_anti_cycle_ok(cover_entity, 1):  # 1 мин для немедленного закрытия
            continue
        
        if is_door:
            # Дверь: закрываем на away_pct
            pos = 100 - away_pct
            _cv_set_cover_position(cover_entity, pos, mode)
            _cv_log("leave", "INFO", cid + ": immediate close to " + str(pos) + "% (door)")
        else:
            # Обычная: закрываем полностью
            _cv_close_cover(cover_entity, mode)
            _cv_log("leave", "INFO", cid + ": immediate close (ordinary)")


def _cv_tick():
    """Основной цикл согласования."""
    if _REGISTRY is None:
        return
    
    cfg = _cv_cfg()
    if not cfg or not cfg.get("enabled", True):
        return
    
    # Проверяем глобальный флаг
    if _cv_state("input_boolean.feature_covers") == "off":
        return
    
    mode = _cv_mode(cfg)
    covers_list = cfg.get("covers", [])
    
    # Читаем флаги присутствия
    presence_flag = cfg.get("presence_flag", "input_boolean.my_doma")
    home = _cv_state(presence_flag) == "on"
    dogs = _cv_state("input_boolean.dogs_home") == "on"
    
    for c in covers_list:
        try:
            _cv_apply_cover(c, cfg, mode, home, dogs)
        except Exception as exc:
            _cv_log("error", "ERROR", "cover " + str(c.get("id")) + " error: " + str(exc))


@time_trigger("startup")
def covers_controller_loop():
    """Главный цикл контроллера штор."""
    log.info("[covers] Controller loop started")
    while True:
        try:
            _cv_tick()
        except Exception as exc:
            log.error("[covers] Controller error: " + str(exc))
        task.sleep(60)


# ---------------- мгновенная реакция на уход ----------------

def _cv_presence_build_list():
    """Список сущностей для триггера присутствия."""
    cfg = _cv_cfg() or {}
    pf = cfg.get("presence_flag", "input_boolean.my_doma")
    return [pf] if pf else ["input_boolean.my_doma"]


_CV_PRESENCE_LIST = _cv_presence_build_list()


@state_trigger(*_CV_PRESENCE_LIST)
def _cv_presence_handler(var_name=None, **kwargs):
    """Обработчик изменения присутствия."""
    if _cv_state("input_boolean.feature_covers") == "off":
        return
    
    cfg = _cv_cfg()
    if not cfg:
        return
    
    # Проверяем: перешли в off (ушли)?
    cur = _cv_state(var_name)
    if cur != "off":
        return
    
    # Немедленное закрытие
    covers_list = cfg.get("covers", [])
    _cv_immediate_close_on_leave(cfg, covers_list)


# ---------------- сервис отладки ----------------

@service
def covers_debug():
    """Сервис отладки: вывод статуса всех штор."""
    cfg = _cv_cfg()
    if not cfg:
        log.warning("[covers][debug] no config")
        return {"ok": False}
    
    presence_flag = cfg.get("presence_flag", "input_boolean.my_doma")
    home = _cv_state(presence_flag) == "on"
    dogs = _cv_state("input_boolean.dogs_home") == "on"
    mode = _cv_mode(cfg)
    
    log.warning("[covers][debug] mode=" + str(mode) + " home=" + str(home) + " dogs=" + str(dogs))
    
    covers_list = cfg.get("covers", [])
    for c in covers_list:
        cid = str(c.get("id"))
        cover_entity = c.get("cover")
        
        dec = _cv_decide_cover(c, cfg, home, dogs)
        actual = _cv_get_actual_position(cover_entity)
        ovr = _cv_override_active(cover_entity)
        auto_flag = _cv_state("input_boolean.cover_%s_auto" % cid)
        
        desired_str = str(dec) if dec else "N/A"
        actual_str = str(actual) if actual is not None else "N/A"
        ovr_str = "active" if ovr else "none"
        auto_str = auto_flag if auto_flag else "missing"
        
        log.warning("[covers][debug] " + cid + ": auto=" + auto_str + " desired=" + desired_str + " actual=" + actual_str + " override=" + ovr_str)
    
    # Создаём виртуальный сенсор для диагностики
    state.set("sensor.covers_debug", "ok", 
              home=home, dogs=dogs, mode=mode, count=len(covers_list))
    
    return {"ok": True, "home": home, "dogs": dogs, "mode": mode}


# ---------------- сервис очистки override ----------------

@service
def covers_override_clear(entity=None):
    """Очистка override."""
    if entity:
        _CV_OVERRIDE.pop(entity, None)
    else:
        _CV_OVERRIDE.clear()
    return {"ok": True}
