# ============================================================
# RUNTIME-ОБВЯЗКА manifest_loader
# Конкатенируется deploy-скриптом ПОСЛЕ registry.py.
# ============================================================
import os
import yaml
import builtins

try:
    CONFIG_DIR = hass.config.config_dir  # noqa
except NameError:
    CONFIG_DIR = "/config"

DEFAULT_MANIFEST_PATH = os.path.join(CONFIG_DIR,"manifests","active.yaml")

_REGISTRY = None
_MANIFEST_PATH = DEFAULT_MANIFEST_PATH

# ============================================================
# СИСТЕМА ЛОГИРОВАНИЯ
# ============================================================
_LOG_CACHE = {}  # кэш уровней: {domain: level_index}
_LOG_LEVELS = ["Выкл", "Ошибки", "Предупреждения", "Инфо", "Отладка"]
_LOG_DOMAINS = []  # список доменов из реестра
_DECISION_BUFFER = []  # кольцевой буфер решений (последние 50)

def _lg_get_level_index(level_name):
    """Получить индекс уровня по названию."""
    for idx, name in enumerate(_LOG_LEVELS):
        if name == level_name:
            return idx
    return 3  # fallback: Инфо


def _lg_refresh_cache():
    """Обновить кэш уровней логирования из helpers."""
    global _LOG_CACHE, _LOG_DOMAINS
    # Платформа
    plat_lvl = _lg_state("input_select.loglevel_platform") or "Инфо"
    _LOG_CACHE["platform"] = _lg_get_level_index(plat_lvl)
    
    # Фичи
    for domain in _LOG_DOMAINS:
        entity = "input_select.loglevel_" + domain
        lvl = _lg_state(entity) or "Инфо"
        _LOG_CACHE[domain] = _lg_get_level_index(lvl)


def log_event(domain, level_name, message, why="", src="автоматика", **kwargs):
    """
    Единый диспетчер логирования.
    domain: 'platform', 'lighting', 'climate', 'ventilation', 'sensor_health'
    level_name: 'Ошибки', 'Предупреждения', 'Инфо', 'Отладка'
    message: текст события
    why: причина решения
    src: источник (автоматика/ручное/Алиса-внешний/таймер/датчик)
    kwargs: дополнительные ключи для лога
    """
    global _LOG_CACHE, _DECISION_BUFFER
    
    # Проверка: есть ли домен в кэше
    if domain not in _LOG_CACHE:
        _lg_refresh_cache()
    
    # Получить требуемый уровень
    req_level_idx = _lg_get_level_index(level_name)
    cached_idx = _LOG_CACHE.get(domain, 3)
    
    # Фильтрация: если уровень ниже кэшированного — не логировать
    if req_level_idx > cached_idx:
        return
    
    # Форматирование дополнительных ключей
    extra_parts = []
    for k, v in kwargs.items():
        extra_parts.append("%s=%s" % (str(k), str(v)))
    
    extra_str = ""
    if extra_parts:
        extra_str = " | " + " | ".join(extra_parts)
    
    why_str = ""
    if why:
        why_str = " | why=" + str(why)
    
    # Единый формат строки лога
    log_line = "[" + domain + "][" + level_name + "] " + str(message) + why_str + " | src=" + str(src) + extra_str
    
    # Вывод через log.info или log.warning в зависимости от уровня
    if level_name == "Отладка":
        log.debug(log_line)
    elif level_name == "Инфо":
        log.info(log_line)
    elif level_name == "Предупреждения":
        log.warning(log_line)
    else:  # Ошибки, Выкл
        log.error(log_line)
    
    # Добавление в буфер решений (только важные события)
    if level_name in ["Инфо", "Предупреждения", "Ошибки"]:
        _add_to_buffer(domain, message, why, src)


def _add_to_buffer(domain, decision, reason, source):
    """Добавить решение в кольцевой буфер."""
    global _DECISION_BUFFER
    import time
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "time": now,
        "domain": domain,
        "decision": decision,
        "reason": reason or "",
        "source": source
    }
    _DECISION_BUFFER.insert(0, entry)
    # Обрезать до 50 записей
    if len(_DECISION_BUFFER) > 50:
        _DECISION_BUFFER = _DECISION_BUFFER[:50]
    # Опубликовать в sensor.platform_decisions
    _publish_decisions()


def _publish_decisions():
    """Опубликовать буфер решений в sensor.platform_decisions."""
    try:
        state.set("sensor.platform_decisions", len(_DECISION_BUFFER),
                  decisions=_DECISION_BUFFER)
    except Exception:
        pass


@state_trigger("{input_select.loglevel_platform,input_select.loglevel_lighting,input_select.loglevel_climate,input_select.loglevel_ventilation,input_select.loglevel_sensor_health,input_select.loglevel_covers}")
def _loglevel_changed(**kwargs):
    """Обработчик изменения уровня логирования."""
    _lg_refresh_cache()
    log_event("platform", "Инфо", "Уровень логирования обновлён", src="ручное")


@time_trigger("startup")
def _fsm_restore_on_startup():
    """Восстановление FSM-состояний сразу после старта."""
    fsm_load_states()


@time_trigger("startup")
def _logging_startup():
    """Инициализация логирования при старте."""
    global _LOG_DOMAINS
    # Домены будут заполнены после загрузки реестра
    _LOG_DOMAINS = ["lighting", "climate", "ventilation", "sensor_health", "covers"]
    _lg_refresh_cache()
    log_event("platform", "Инфо", "Система логирования запущена", src="таймер")
    
    # Периодическое обновление кэша (раз в минуту)
    while True:
        task.sleep(60)
        _lg_refresh_cache()


def _read_manifest_file(path):
    """Чтение манифеста. Использует инъекцию из build-скрипта для дефолтного пути (0 blocking I/O)."""
    # Если это дефолтный путь и есть инъекция — возвращаем готовый словарь
    if path == DEFAULT_MANIFEST_PATH:
        try:
            if INJECTED_MANIFEST_DATA is not None:
                return INJECTED_MANIFEST_DATA
        except NameError:
            pass
    # Fallback: чтение с диска (только для явных вызовов manifest_load с другим путем)
    import yaml as _yaml
    import builtins as _builtins
    fh = _builtins.open(path, "r", encoding="utf-8")
    content = fh.read()
    fh.close()
    return _yaml.safe_load(content)


def _collect_missing_helpers(registry):
    existing = set(state.names())
    missing = []
    for h in registry.required_helpers():
        if h not in existing:
            missing.append(h)
    return missing


def _do_load(path=None):
    global _REGISTRY, _MANIFEST_PATH
    if path:
        _MANIFEST_PATH = path

    log.info("[manifest] Загрузка манифеста:" + str(_MANIFEST_PATH))

    use_injected = (_MANIFEST_PATH == DEFAULT_MANIFEST_PATH)
    try:
        use_injected = use_injected and (INJECTED_MANIFEST_DATA is not None)
    except NameError:
        use_injected = False
    if not use_injected and not os.path.exists(_MANIFEST_PATH):
        log.error("[manifest] Файл не найден: " + str(_MANIFEST_PATH))
        return {"ok": False, "error": "manifest not found: " + str(_MANIFEST_PATH)}

    raw = None
    try:
        raw = _read_manifest_file(_MANIFEST_PATH)
    except Exception as exc:
        log.error("[manifest] Ошибка чтения YAML:" + str(exc))
        return {"ok": False,"error":"yaml parse error"}

    log.info("[manifest] YAML прочитан, тип:" + str(type(raw)))

    reg = None
    try:
        reg = build_registry(raw)
    except Exception as exc:
        log.error("[manifest] Ошибка построения реестра:" + str(exc))
        return {"ok": False,"error":"registry build error"}

    _REGISTRY = reg
    s = reg.summary()
    
    # Краткий лог о загрузке модулей
    features_loaded = []
    features_missing = []
    for feat in ["lighting", "climate", "ventilation", "sensor_health"]:
        if reg.feature(feat):
            features_loaded.append(feat)
        else:
            features_missing.append(feat)
    
    log.info("[manifest] Загружен инстанс:" + str(s.get("instance"))
             + ", устройств: " + str(s.get("devices")))
    log.info("[manifest] Модули: " + ", ".join(["%s: ок" % f for f in features_loaded])
             + (", ".join(["%s: нет" % f for f in features_missing]) if features_missing else ""))
    return {"ok": True, "summary": s}


@service
def manifest_load(path=None):
    return _do_load(path)


@service
def manifest_reload():
    return _do_load(_MANIFEST_PATH)


@service
def manifest_status():
    log.warning("[manifest][status] сервис вызван")
    if _REGISTRY is None:
        result = {"ok": False,"error":"manifest not loaded"}
        log.warning("[manifest][status]" + str(result))
        return result
    missing = _collect_missing_helpers(_REGISTRY)
    result = {
        "ok": True,"summary": _REGISTRY.summary(),"missing_helpers": missing,"manifest_path": _MANIFEST_PATH,
    }
    log.warning("[manifest][status]" + str(result))
    return result


@service
def manifest_debug():
    """Диагностика: ключевые факты о состоянии загрузчика."""
    log.warning("[manifest][debug] === START ===")
    log.warning("[manifest][debug] _MANIFEST_PATH =" + str(_MANIFEST_PATH))
    log.warning("[manifest][debug] file exists =" + str(os.path.exists(_MANIFEST_PATH)))
    log.warning("[manifest][debug] _REGISTRY is None =" + str(_REGISTRY is None))
    if _REGISTRY is not None:
        log.warning("[manifest][debug] summary =" + str(_REGISTRY.summary()))
    log.warning("[manifest][debug] === END ===")
    return {"ok": True}


@service
def manifest_provision_helpers():
    if _REGISTRY is None:
        return {"ok": False,"error":"manifest not loaded"}
    missing = _collect_missing_helpers(_REGISTRY)
    booleans = []
    numbers = []
    for m in missing:
        if m.startswith("input_boolean."):
            booleans.append(m)
        elif m.startswith("input_number."):
            numbers.append(m)

    lines = ["# Добавьте в configuration.yaml:",""]
    if booleans:
        lines.append("input_boolean:")
        for b in booleans:
            name = b.split(".", 1)[1]
            lines.append("" + name + ":")
            lines.append("    name:" + name)
    if numbers:
        lines.append("input_number:")
        for n in numbers:
            name = n.split(".", 1)[1]
            lines.append("" + name + ":")
            lines.append("    name:" + name)
            lines.append("    min: 5")
            lines.append("    max: 35")
            lines.append("    step: 0.5")
            lines.append("    unit_of_measurement: '°C'")

    snippet ="\n".join(lines)
    log.warning("[manifest] Сгенерирован snippet helpers:\n" + snippet)
    return {"ok": True,"missing": missing,"yaml_snippet": snippet}


@service
def feature_set_enabled(feature: str, enabled: bool):
    entity ="input_boolean.feature_" + str(feature)
    if entity not in state.names():
        log.warning("[manifest]" + entity + " не существует. Создайте его.")
        return {"ok": False,"error": entity +" not found"}
    svc ="turn_on" if enabled else"turn_off"
    service.call("input_boolean", svc, entity_id=entity)
    return {"ok": True,"feature": feature,"enabled": enabled}


# Первичная загрузка при старте
_do_load()


# ==================== PLATFORM DOCTOR ====================

@service
def platform_doctor():
    """Структурированный диагноз платформы: FSM-состояния, проблемы, решения.

    Результат: лог + sensor.platform_doctor (атрибут doctor = JSON).
    """
    import json
    doc = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "fsm": {}, "problems": [], "recent_decisions": []}

    # Все опубликованные FSM-состояния
    try:
        for st in hass.states.all():
            eid = str(st.entity_id)
            if eid.endswith("_fsm_state"):
                doc["fsm"][eid] = st.state
    except Exception as exc:
        doc["fsm"]["error"] = str(exc)

    # Проблемы здоровья (недоступные сенсоры, батарейки, расхождения, зависания)
    try:
        shcfg = (_REGISTRY.feature("sensor_health") if _REGISTRY is not None else {}) or {}
        doc["problems"] = _sh_problems(shcfg)
    except Exception as exc:
        doc["problems"] = [{"entity": "sensor_health", "reason": str(exc)}]

    # Последние решения
    try:
        doc["recent_decisions"] = list(_DECISION_BUFFER[:10])
    except Exception:
        pass

    # Расхождения света отдельно для наглядности
    try:
        doc["light_states"] = {
            str(g.get("id")): fsm_get_state("light." + str(g.get("id")))
            for g in ((_lg_cfg() or {}).get("groups", []) or [])
        }
    except Exception as exc:
        doc["light_states"] = {"error": str(exc)}

    ok = not doc["problems"]
    try:
        state.set("sensor.platform_doctor", "ok" if ok else "issues",
                  doctor=json.dumps(doc, ensure_ascii=False))
    except Exception:
        pass
    log.info("[doctor] %d FSM, %d problems" % (len(doc["fsm"]), len(doc["problems"])))
    return doc
