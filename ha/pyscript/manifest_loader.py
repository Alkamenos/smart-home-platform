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

DEFAULT_MANIFEST_PATH = os.path.join(CONFIG_DIR, "manifests", "active.yaml")

_REGISTRY = None
_MANIFEST_PATH = DEFAULT_MANIFEST_PATH


def _read_manifest_file(path):
    # БЕЗ with: pyscript теряет return из with-блока
    fh = builtins.open(path, "r", encoding="utf-8")
    content = fh.read()
    fh.close()
    return yaml.safe_load(content)


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

    log.info("[manifest] Загрузка манифеста: " + str(_MANIFEST_PATH))

    if not os.path.exists(_MANIFEST_PATH):
        log.error("[manifest] Файл не найден: " + str(_MANIFEST_PATH))
        return {"ok": False, "error": "manifest not found: " + str(_MANIFEST_PATH)}

    raw = None
    try:
        raw = _read_manifest_file(_MANIFEST_PATH)
    except Exception as exc:
        log.error("[manifest] Ошибка чтения YAML: " + str(exc))
        return {"ok": False, "error": "yaml parse error"}

    log.info("[manifest] YAML прочитан, тип: " + str(type(raw)))

    reg = None
    try:
        reg = build_registry(raw)
    except Exception as exc:
        log.error("[manifest] Ошибка построения реестра: " + str(exc))
        return {"ok": False, "error": "registry build error"}

    _REGISTRY = reg
    s = reg.summary()
    log.info("[manifest] Загружен инстанс: " + str(s.get("instance"))
             + ", устройств: " + str(s.get("devices")))
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
        result = {"ok": False, "error": "manifest not loaded"}
        log.warning("[manifest][status] " + str(result))
        return result
    missing = _collect_missing_helpers(_REGISTRY)
    result = {
        "ok": True,
        "summary": _REGISTRY.summary(),
        "missing_helpers": missing,
        "manifest_path": _MANIFEST_PATH,
    }
    log.warning("[manifest][status] " + str(result))
    return result


@service
def manifest_debug():
    """Диагностика: ключевые факты о состоянии загрузчика."""
    log.warning("[manifest][debug] === START ===")
    log.warning("[manifest][debug] _MANIFEST_PATH = " + str(_MANIFEST_PATH))
    log.warning("[manifest][debug] file exists = " + str(os.path.exists(_MANIFEST_PATH)))
    log.warning("[manifest][debug] _REGISTRY is None = " + str(_REGISTRY is None))
    if _REGISTRY is not None:
        log.warning("[manifest][debug] summary = " + str(_REGISTRY.summary()))
    log.warning("[manifest][debug] === END ===")
    return {"ok": True}


@service
def manifest_provision_helpers():
    if _REGISTRY is None:
        return {"ok": False, "error": "manifest not loaded"}
    missing = _collect_missing_helpers(_REGISTRY)
    booleans = []
    numbers = []
    for m in missing:
        if m.startswith("input_boolean."):
            booleans.append(m)
        elif m.startswith("input_number."):
            numbers.append(m)

    lines = ["# Добавьте в configuration.yaml:", ""]
    if booleans:
        lines.append("input_boolean:")
        for b in booleans:
            name = b.split(".", 1)[1]
            lines.append("  " + name + ":")
            lines.append("    name: " + name)
    if numbers:
        lines.append("input_number:")
        for n in numbers:
            name = n.split(".", 1)[1]
            lines.append("  " + name + ":")
            lines.append("    name: " + name)
            lines.append("    min: 5")
            lines.append("    max: 35")
            lines.append("    step: 0.5")
            lines.append("    unit_of_measurement: '°C'")

    snippet = "\n".join(lines)
    log.warning("[manifest] Сгенерирован snippet helpers:\n" + snippet)
    return {"ok": True, "missing": missing, "yaml_snippet": snippet}


@service
def feature_set_enabled(feature: str, enabled: bool):
    entity = "input_boolean.feature_" + str(feature)
    if entity not in state.names():
        log.warning("[manifest] " + entity + " не существует. Создайте его.")
        return {"ok": False, "error": entity + " not found"}
    svc = "turn_on" if enabled else "turn_off"
    service.call("input_boolean", svc, entity_id=entity)
    return {"ok": True, "feature": feature, "enabled": enabled}


# Первичная загрузка при старте
_do_load()