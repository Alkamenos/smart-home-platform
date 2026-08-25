#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# venv: CLI shplatform и pyyaml живут там
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . ".venv/bin/activate"
fi

HA_URL="${HA_URL:-http://homeassistant.local:8123}"
HA_TOKEN="${HA_TOKEN:-$(cat ~/.ha_token 2>/dev/null || true)}"
HA_CONFIG="${HA_CONFIG:-/config}"

echo "== 1. validate =="
shplatform validate instances/${INSTANCE:-leonid_house}/manifest.yaml

echo "== 2. concat =="
{ cat shplatform/loader/registry.py; echo ""; \
  cat ha/pyscript/manifest_loader.py; echo ""; \
  cat features/climate/runtime.py; echo ""; \
  cat features/ventilation/runtime.py; echo ""; \
  cat features/health/runtime.py; echo ""; \
  cat ha/pyscript/lighting_controller.py; } > "$HA_CONFIG/pyscript/manifest_loader.py"

echo "== 3. sanity: generator expressions запрещены =="
if grep -nE "\b(any|all|sum|min|max|join)\(" "$HA_CONFIG/pyscript/manifest_loader.py" \
    | grep " for " | grep -v "\["; then
  echo "FAIL: найдены generator expressions (см. docs/PYSCRIPT_RULES.md)"; exit 1
fi
echo "OK"

echo "== 4. sync manifest =="
mkdir -p "$HA_CONFIG/manifests"
cp instances/${INSTANCE:-leonid_house}/manifest.yaml "$HA_CONFIG/manifests/active.yaml"

if [ "${1:-}" = "--smoke" ]; then exec python3 tools/smoke_light.py; fi

echo "== 5. restart HA =="
if [ -n "$HA_TOKEN" ]; then
  read -r -p "Перезапустить HA сейчас? [y/N] " a
  if [ "$a" = "y" ]; then
    curl -fs -X POST "$HA_URL/api/services/homeassistant/restart" \
      -H "Authorization: Bearer $HA_TOKEN" -H "Content-Type: application/json" > /dev/null
    echo "Рестарт запрошен. После подъёма: ./tools/deploy.sh --smoke"
  fi
else
  echo "HA_TOKEN не задан (создай long-lived token в ~/.ha_token). Рестартни HA вручную, затем ./tools/deploy.sh --smoke"
fi
