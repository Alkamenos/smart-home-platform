#!/bin/sh
# Точка входа аддона Home Assistant (B79).
#
# Supervisor кладёт опции аддона в /data/options.json и (при homeassistant_api:
# true) — токен в SUPERVISOR_TOKEN. Здесь опции переводятся в переменные
# окружения платформы, а дальше работает штатная точка входа образа: она сеет
# конфигурацию в пустой каталог и запускает платформу.
#
# Чего здесь НЕТ: длинного токена Home Assistant. Адрес и токен даёт Supervisor,
# поэтому ротировать и шифровать нечего — это и есть выигрыш аддона.

set -eu

OPTIONS=/data/options.json

#: Прочитать опцию аддона (значение по умолчанию, если её нет).
option() {
    python - "$OPTIONS" "$1" "$2" <<'PY'
import json
import pathlib
import sys

path, key, default = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
value = data.get(key, default)
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

# Home Assistant для аддона — прокси Supervisor. Токен подставлен Supervisor'ом.
export HA_URL="http://supervisor/core"
export HA_WEBSOCKET_URL="ws://supervisor/core/websocket"
export HA_TOKEN="${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN не задан: у аддона должен быть homeassistant_api: true}"

# Манифест и данные — в addon_config, чтобы попадать в резервные копии HA.
export CONFIG_PATH="/addon_config/config"
export DATA_PATH="/addon_config/data"
export CONFIG_SEED_PATH="/app/instances/leonids_house_prod"

export LOG_LEVEL="$(option log_level info)"
export SHADOW_MODE="$(option shadow_mode false)"
export HOUSE_TIMEZONE="$(option timezone Asia/Yekaterinburg)"
export WEBUI_SERVE_FRONTEND=1

echo "Аддон: HA=$HA_URL, конфигурация в $CONFIG_PATH, данные в $DATA_PATH"
echo "Аддон: уровень журнала $LOG_LEVEL, теневой режим $SHADOW_MODE, пояс $HOUSE_TIMEZONE"

# Штатная точка входа образа: сеет конфигурацию в пустой каталог и запускает CMD.
exec /app/deploy/docker/docker-entrypoint.sh "$@"
