#!/usr/bin/env python3
"""Глобальные переменные состояния и хелперы чтения для lighting feature."""

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================

# Предыдущее состояние ламп (для детекта изменений)
_LG_PREV = {}

# Блокировки override по entity_id -> timestamp
_LG_OVERRIDE = {}

# Время последнего изменения лампы (для anti-cycle)
_LG_LAST_CHANGE = {}

# Последнее detected движение по gid
_LG_MOTION_LAST = {}

# Статус темноты (с гистерезисом)
_DARK = None

# Время последней смены цветовой температуры по entity
_CT_LAST = {}

# Предыдущее состояние vlight entities
_VLIGHT_PREV = {}

# Guard для синхронизации vlight (чтобы избежать циклов)
_VLIGHT_SYNC_GUARD = {}

# Ожидаемое состояние实体 (для фильтра команд платформы от внешних)
_EXPECTED_REAL_STATE = {}

# Маппинг кнопок -> действия
_BUTTON_MAP = {}

# Активная имитация присутствия: entity -> (until_timestamp, gid)
_LG_IM_ACTIVE = {}

# Лампы в режиме ночника
_LG_NL_ACTIVE = set()

# Применённые RGB сцены по entity
_RGB_APPLIED = {}

# Кэш caps по gid
_LG_CAPS = {}

# Глобальная настройка логирования
_LOG_LEVELS = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3, "DEBUG": 4}
_LOG_LEVEL = _LOG_LEVELS.get("INFO", 3)  # по умолчанию
_MODULE_LOG_LEVELS = {}

# Реестр voters (заполняется декоратором @fd_voter)
_FD_REGISTRY = []
_FD_ABORT = {"abort": True}


# ==================== ХЕЛПЕРЫ ЧТЕНИЯ СОСТОЯНИЙ ====================

def _lg_state(entity):
    """Безопасное чтение состояния entity."""
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.state


def _lg_attr(entity, name):
    """Безопасное чтение атрибута entity."""
    st = hass.states.get(entity)
    if st is None:
        return None
    return st.attributes.get(name)


def _lg_get_float(entity):
    """Чтение числового состояния с обработкой ошибок."""
    s = _lg_state(entity)
    if s is None:
        return None
    if str(s) in ("unknown", "unavailable", "none", ""):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _lg_is_on(e):
    """Проверка, включена ли сущность."""
    return _lg_state(e) == "on"


def _lg_unavailable(e):
    """Проверка недоступности сущности."""
    s = _lg_state(e)
    return s is None or str(s) in ("unknown", "unavailable")


def _lg_num(entity, default):
    """Чтение числа из input_number или fallback."""
    s = _lg_state(entity)
    if s is None:
        return default
    try:
        return float(s)
    except Exception:
        return default


# ==================== ВРЕМЯ ====================

def _lg_now_min():
    """Текущее время в минутах от начала суток."""
    t = time.localtime()
    return t.tm_hour * 60 + t.tm_min


def _lg_hm(s):
    """Парсинг HH:MM в минуты."""
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _lg_dt_min(entity):
    """Чтение времени из input_datetime в минуты."""
    s = _lg_state(entity)
    if not s:
        return None
    try:
        parts = str(s).split(" ")
        t = parts[1] if len(parts) > 1 else parts[0]
        return _lg_hm(t[:5])
    except Exception:
        return None


# ==================== КОНФИГУРАЦИЯ ====================

def _lg_init_logging():
    """Инициализация уровней логирования из манифеста."""
    global _LOG_LEVEL, _MODULE_LOG_LEVELS
    if _REGISTRY is None:
        return
    cfg = _REGISTRY.feature("logging") or {}
    level_name = cfg.get("level", "INFO")
    _LOG_LEVEL = _LOG_LEVELS.get(level_name, 3)
    modules = cfg.get("modules", {})
    for mod, lvl in modules.items():
        _MODULE_LOG_LEVELS[mod] = _LOG_LEVELS.get(lvl, 3)


def _lg_log(module, level_name, msg):
    """Логирование с проверкой уровня."""
    level_val = _LOG_LEVELS.get(level_name, 3)
    module_level = _MODULE_LOG_LEVELS.get(module, _LOG_LEVEL)
    if level_val <= module_level:
        if level_name == "DEBUG":
            log.info("[light][DEBUG][" + module + "] " + msg)
        elif level_name == "INFO":
            log.info("[light][" + module + "] " + msg)
        else:
            log.warning("[light][" + module + "] " + msg)


def _lg_cfg():
    """Получение конфигурации освещения из реестра."""
    if _REGISTRY is None:
        return None
    # Инициализация логирования при первом вызове
    _lg_init_logging()
    cfg = _REGISTRY.feature("lighting") or None
    if not cfg:
        return None
    out = dict(cfg)
    raw_groups = _REGISTRY.feature("groups") or out.get("groups") or []
    groups = []
    for g in raw_groups:
        if not isinstance(g, dict):
            continue
        try:
            groups.append(resolve_group(g))
        except Exception as ex:
            log.warning("[light] resolve failed: %s: %s" % (str(g.get("id")), str(ex)))
    out["groups"] = groups
    im_cfg = out.get("imitation")
    if im_cfg:
        im_cfg = dict(im_cfg)
        gl = list(im_cfg.get("groups", []) or [])
        for g in groups:
            if ((g.get("features") or {}).get("imitation") or {}).get("participate"):
                if str(g.get("id")) not in gl:
                    gl.append(str(g.get("id")))
        im_cfg["groups"] = gl
        out["imitation"] = im_cfg
    return out


# ==================== РЕЖИМЫ И СЕЗОНЫ ====================

def _lg_mode(cfg):
    """Определение текущего режима (real/shadow)."""
    sh = _lg_state("input_boolean.lighting_shadow_mode")
    if sh == "on":
        return "shadow"
    if sh == "off":
        return "real"
    return cfg.get("mode", "real")


def _lg_night(cfg):
    """Проверка ночного флага."""
    return _lg_state(cfg.get("night_flag", "input_boolean.vecher")) == "on"


def _lg_season(g):
    """Применение сезонных настроек к группе."""
    s = g.get("season")
    if not s:
        return g
    zima = _lg_state("input_boolean.zima") == "on"
    var = s.get("winter") if zima else s.get("summer")
    if not var:
        return g
    merged = dict(g)
    merged.update(var)
    return merged


# ==================== ДАТЧИКИ ДВИЖЕНИЯ ====================

def _lg_motion_sensor(g, gid):
    """Прочитать текущий датчик движения из helper'а или манифеста."""
    helper = "input_select.light_%s_motion_sensor" % gid
    val = _lg_state(helper)
    if val and val not in ("unknown", "unavailable", ""):
        return val
    return g.get("motion_sensor")


def _lg_motion(g, gid):
    """Проверка наличия движения для группы."""
    ms = _lg_motion_sensor(g, gid)
    if not ms:
        return None
    return _lg_state(ms) in ("on", "true", True)


# ==================== ТЕМНОТА (ГИСТЕРЕЗИС) ====================

def _lg_update_dark(cfg):
    """Обновление статуса темноты с гистерезисом."""
    global _DARK
    d = cfg.get("dark", {}) or {}
    lux = None
    if d.get("illuminance_sensor"):
        lux = _lg_get_float(d["illuminance_sensor"])
    if lux is not None:
        if _DARK is None:
            _DARK = lux < d.get("dark_lux", 20)
        elif _DARK and lux > d.get("light_lux", 40):
            _DARK = False
        elif (not _DARK) and lux < d.get("dark_lux", 20):
            _DARK = True
        return
    try:
        elev = float(hass.states.get("sun.sun").attributes.get("elevation", 99))
    except Exception:
        return
    if _DARK is None:
        _DARK = elev < d.get("sun_dark_elevation", -3)
    elif _DARK and elev > d.get("sun_light_elevation", 1):
        _DARK = False
    elif (not _DARK) and elev < d.get("sun_dark_elevation", -3):
        _DARK = True


# ==================== VLIGHT ENTITY ====================

def lg_vlight_entity(g):
    """Получение vlight entity для группы."""
    return g.get("vlight_entity") or ("input_boolean.vlight_" + str(g.get("id")))
