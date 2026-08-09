"""Manifest Loader для Home Assistant (pyscript).

Загружает провалидированный манифест, строит runtime-реестр, проверяет
наличие helper-сущностей и предоставляет сервисы управления.

Требования:
  1. Интеграция pyscript (HACS) установлена.
  2. В configuration.yaml:
        pyscript:
          allow_all_imports: true
          hass_is_global: true
  3. В папке <config>/pyscript/ рядом лежит registry.py
     (копия shplatform/loader/registry.py).

Предоставляемые сервисы (домен pyscript):
  - pyscript.manifest_load(path=None)
  - pyscript.manifest_reload()
  - pyscript.manifest_status()
  - pyscript.manifest_provision_helpers()
  - pyscript.feature_set_enabled(feature, enabled)
"""
import os
import sys

import yaml

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
try:
    CONFIG_DIR = hass.config.config_dir  # noqa: F821 (hass_is_global: true)
except NameError:
    CONFIG_DIR = "/config"

PYSCRIPT_DIR = os.path.join(CONFIG_DIR, "pyscript")
DEFAULT_MANIFEST_PATH = os.path.join(CONFIG_DIR, "manifests", "active.yaml")

# Делаем папку pyscript/ видимой для import
if PYSCRIPT_DIR not in sys.path:
    sys.path.insert(0, PYSCRIPT_DIR)

# Импортируем registry как обычный модуль.
# Сбрасываем кэш, чтобы при pyscript.reload подхватывались изменения registry.py
try:
    if "registry" in sys.modules:
        del sys.modules["registry"]
    from registry import build_registry, ManifestError
    _REGISTRY_OK = True
except Exception as exc:
    log.error(f"[manifest] Не удалось импортировать registry.py: {exc}")
    build_registry = None
    ManifestError = Exception
    _REGISTRY_OK = False

# ---------------------------------------------------------------------------
# Глобальное runtime-состояние модуля
# ---------------------------------------------------------------------------
_REGISTRY = None
_MANIFEST_PATH = DEFAULT_MANIFEST_PATH


# ---------------------------------------------------------------------------
# Внутренние функции
# ---------------------------------------------------------------------------
def _check_helpers(registry):
    existing = set(state.names())
    missing = [h for h in registry.required_helpers() if h not in existing]
    if missing:
        log.warning(f"[manifest] Отсутствуют helper-сущности: {missing}")
    return missing


def _do_load(path=None):
    global _REGISTRY, _MANIFEST_PATH

    if not _REGISTRY_OK:
        return None, {"ok": False, "error": "registry.py import failed"}

    if path:
        _MANIFEST_PATH = path

    log.info(f"[manifest] Загрузка манифеста: {_MANIFEST_PATH}")

    if not os.path.exists(_MANIFEST_PATH):
        log.error(f"[manifest] Файл не найден: {_MANIFEST_PATH}")
        return None, {"ok": False, "error": f"manifest not found: {_MANIFEST_PATH}"}

    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as exc:
        log.error(f"[manifest] Ошибка парсинга YAML: {exc}")
        return None, {"ok": False, "error": f"yaml parse: {exc}"}

    try:
        registry = build_registry(raw)
    except ManifestError as exc:
        log.error(f"[manifest] Ошибка построения реестра: {exc}")
        return None, {"ok": False, "error": f"registry: {exc}"}

    _REGISTRY = registry
    _check_helpers(registry)
    s = registry.summary()
    log.info(f"[manifest] Загружен инстанс '{s['instance']}', устройств: {s['devices']}")
    return registry, {"ok": True, **s}


# ---------------------------------------------------------------------------
# Сервисы pyscript
# ---------------------------------------------------------------------------
@service
def manifest_load(path=None):
    """Загрузить манифест (опционально указать путь)."""
    _, report = _do_load(path)
    return report


@service
def manifest_reload():
    """Перечитать манифест с диска."""
    _, report = _do_load(_MANIFEST_PATH)
    return report


@service
def manifest_status():
    """Сводка по манифесту и недостающим helpers."""
    if _REGISTRY is None:
        return {"ok": False, "error": "manifest not loaded"}
    existing = set(state.names())
    missing = [h for h in _REGISTRY.required_helpers() if h not in existing]
    return {
        "ok": True,
        **_REGISTRY.summary(),
        "missing_helpers": missing,
        "manifest_path": _MANIFEST_PATH,
    }


@service
def manifest_provision_helpers():
    """Сгенерировать YAML-сниппет для создания недостающих helpers."""
    if _REGISTRY is None:
        return {"ok": False, "error": "manifest not loaded"}

    existing = set(state.names())
    missing = [h for h in _REGISTRY.required_helpers() if h not in existing]

    booleans = [m for m in missing if m.startswith("input_boolean.")]
    numbers = [m for m in missing if m.startswith("input_number.")]

    lines = ["# Добавьте в configuration.yaml:", ""]
    if booleans:
        lines.append("input_boolean:")
        for b in booleans:
            lines.append(f"  {b.split('.', 1)[1]}:")
            lines.append(f"    name: {b.split('.', 1)[1]}")
    if numbers:
        lines.append("input_number:")
        for n in numbers:
            lines.append(f"  {n.split('.', 1)[1]}:")
            lines.append(f"    name: {n.split('.', 1)[1]}")
            lines.append("    min: 5")
            lines.append("    max: 35")
            lines.append("    step: 0.5")
            lines.append("    unit_of_measurement: '°C'")

    snippet = "\n".join(lines)
    log.info(f"[manifest] Сгенерирован snippet helpers:\n{snippet}")
    return {"ok": True, "missing": missing, "yaml_snippet": snippet}


@service
def feature_set_enabled(feature: str, enabled: bool):
    """Включить/выключить фичу через её input_boolean."""
    entity = f"input_boolean.feature_{feature}"
    if entity not in state.names():
        log.warning(f"[manifest] {entity} не существует. Создайте его.")
        return {"ok": False, "error": f"{entity} not found"}
    svc = "turn_on" if enabled else "turn_off"
    service.call("input_boolean", svc, entity_id=entity)
    return {"ok": True, "feature": feature, "enabled": enabled}


# ---------------------------------------------------------------------------
# Первичная загрузка при старте
# ---------------------------------------------------------------------------
_do_load()