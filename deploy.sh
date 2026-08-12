#!/usr/bin/env bash
# Деплой платформы в Home Assistant.
set -euo pipefail

HA_CONFIG="${HA_CONFIG:-}"
MANIFEST_SRC="manifests/leonid_house.yaml"
RELOAD=false
HA_URL=""
HA_TOKEN=""

usage() {
  cat <<'USAGE'
Использование:
  ./deploy.sh --ha-config <путь к конфигу HA> [опции]

Опции:
  --ha-config PATH   Путь к конфигу HA (обязательно, либо переменная HA_CONFIG)
  --manifest PATH    Манифест-источник (по умолчанию manifests/leonid_house.yaml)
  --reload           Перезагрузить pyscript через REST API (рекомендуется полный рестарт HA)
  --ha-url URL       Адрес HA, напр. http://homeassistant.local:8123
  --token TOKEN      Long-lived access token (для --reload)
  -h, --help         Справка
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ha-config) HA_CONFIG="$2"; shift 2 ;;
    --manifest)  MANIFEST_SRC="$2"; shift 2 ;;
    --reload)    RELOAD=true; shift ;;
    --ha-url)    HA_URL="$2"; shift 2 ;;
    --token)     HA_TOKEN="$2"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "Неизвестный аргумент: $1"; usage; exit 1 ;;
  esac
done

[[ -z "$HA_CONFIG" ]] && { echo "✗ Не указан --ha-config"; usage; exit 1; }
[[ -d "$HA_CONFIG" ]] || { echo "✗ Директория конфига не найдена: $HA_CONFIG"; exit 1; }

REGISTRY_SRC="shplatform/loader/registry.py"
LOADER_SRC="ha/pyscript/manifest_loader.py"
ORCHESTRATOR_SRC="ha/pyscript/climate_orchestrator.py"

for f in "$REGISTRY_SRC" "$LOADER_SRC" "$ORCHESTRATOR_SRC" "$MANIFEST_SRC"; do
  [[ -f "$f" ]] || { echo "✗ Не найден файл в репо: $f"; exit 1; }
done

PYSCRIPT_DIR="$HA_CONFIG/pyscript"
MANIFESTS_DIR="$HA_CONFIG/manifests"
mkdir -p "$PYSCRIPT_DIR" "$MANIFESTS_DIR"

TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$HA_CONFIG/.deploy_backup/$TS"

backup_if_exists() {
  local target="$1"
  if [[ -f "$target" ]]; then
    mkdir -p "$BACKUP_DIR"
    cp "$target" "$BACKUP_DIR/$(basename "$target")"
    echo "    backup: $target -> $BACKUP_DIR/"
  fi
}

echo "==> Деплой в $HA_CONFIG"

echo "--> конкатенация registry + manifest_loader + climate_orchestrator"
backup_if_exists "$PYSCRIPT_DIR/manifest_loader.py"
  
VENT_SRC="ha/pyscript/ventilation_controller.py"

{ cat "$REGISTRY_SRC"; echo ""; cat "$LOADER_SRC"; echo ""; cat "$ORCHESTRATOR_SRC"; echo ""; cat "$VENT_SRC"; } \
  > "$PYSCRIPT_DIR/manifest_loader.py"
rm -f "$PYSCRIPT_DIR/registry.py" "$PYSCRIPT_DIR/climate_orchestrator.py"

echo "--> $MANIFEST_SRC -> $MANIFESTS_DIR/active.yaml"
backup_if_exists "$MANIFESTS_DIR/active.yaml"
cp "$MANIFEST_SRC" "$MANIFESTS_DIR/active.yaml"

echo "==> Файлы скопированы."

if [[ "$RELOAD" == true ]]; then
  if [[ -z "$HA_URL" || -z "$HA_TOKEN" ]]; then
    echo "✗ Для --reload нужны --ha-url и --token"; exit 1
  fi
  echo "==> Перезагрузка pyscript через REST API..."
  HTTP_CODE=$(curl -s -o /tmp/pyscript_reload.json -w "%{http_code}" \
    -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" -d '{}' \
    "$HA_URL/api/services/pyscript/reload")
  [[ "$HTTP_CODE" == "200" ]] && echo "    pyscript перезагружен." \
    || { echo "    ⚠ reload вернул HTTP $HTTP_CODE"; cat /tmp/pyscript_reload.json; }
fi

echo "==> Готово. Рекомендуется ПОЛНЫЙ перезапуск HA (избегает дублей фоновых циклов)."