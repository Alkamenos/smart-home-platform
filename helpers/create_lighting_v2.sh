#!/bin/bash
# Скрипт создания helper-сущностей для lighting v2 (vlight + select+time UI)

# Проверка переменных окружения
if [ -z "$HA_URL" ]; then
  echo "❌ Ошибка: HA_URL не установлен!"
  echo "   Пример: export HA_URL=\"http://homeassistant.local:8123\""
  exit 1
fi

if [ -z "$HA_TOKEN" ]; then
  echo "❌ Ошибка: HA_TOKEN не установлен!"
  echo "   Создайте токен в профиле HA и выполните: export HA_TOKEN=\"your_token\""
  exit 1
fi

echo "✅ HA_URL: $HA_URL"
echo "✅ HA_TOKEN: [скрыт]"

# Функция создания input_boolean
create_bool() {
  local entity_id="$1"
  local name="$2"
  echo "Creating $entity_id ($name)"
  response=$(curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"entity_id\": \"$entity_id\", \"name\": \"$name\"}" \
    "$HA_URL/api/services/input_boolean/create")
  http_code=$(echo "$response" | tail -n1)
  if [[ "$http_code" == "200" ]]; then
    echo "  -> ✅ Создан"
  elif [[ "$http_code" == "400" ]]; then
    echo "  -> ⚠️  Уже существует"
  else
    echo "  -> ❌ Ошибка HTTP $http_code"
  fi
}

# Функция создания input_select
create_select() {
  local entity_id="$1"
  local name="$2"
  echo "Creating $entity_id ($name)"
  response=$(curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"entity_id\": \"$entity_id\", \"name\": \"$name\", \"options\": [\"Не включать\", \"Закат\", \"Время\"]}" \
    "$HA_URL/api/services/input_select/create")
  http_code=$(echo "$response" | tail -n1)
  if [[ "$http_code" == "200" ]]; then
    echo "  -> ✅ Создан"
  elif [[ "$http_code" == "400" ]]; then
    echo "  -> ⚠️  Уже существует"
  else
    echo "  -> ❌ Ошибка HTTP $http_code"
  fi
}

# Функция создания input_datetime
create_datetime() {
  local entity_id="$1"
  local name="$2"
  echo "Creating $entity_id ($name)"
  response=$(curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"entity_id\": \"$entity_id\", \"name\": \"$name\", \"has_date\": true, \"has_time\": true}" \
    "$HA_URL/api/services/input_datetime/create")
  http_code=$(echo "$response" | tail -n1)
  if [[ "$http_code" == "200" ]]; then
    echo "  -> ✅ Создан"
  elif [[ "$http_code" == "400" ]]; then
    echo "  -> ⚠️  Уже существует"
  else
    echo "  -> ❌ Ошибка HTTP $http_code"
  fi
}

# Группы из манифеста (явный список для надёжности)
# Формат: "group_id:Group Name"
GROUPS=(
  "yard_floodlights:Улица/двор"
  "front_door:Входная дверь"
  "garage_gate:Ворота гаража"
  "garden_path:Садовая дорожка"
  "terrace:Терраса"
  "balcony:Балкон"
  "bedroom:Спальня"
  "nursery:Детская"
  "office:Кабинет"
  "kitchen:Кухня"
  "bathroom:Санузел"
  "hallway:Коридор"
)

echo "=== Создание vlight и select+time UI для освещения (${#GROUPS[@]} групп) ==="

for item in "${GROUPS[@]}"; do
  gid="${item%%:*}"
  gname="${item#*:}"
  
  echo ""
  echo "Группа: $gid ($gname)"
  
  # vlight toggle
  create_bool "input_boolean.vlight_${gid}" "vlight: $gname"
  
  # select for on-mode
  create_select "input_select.light_${gid}_on" "Режим включения: $gname"
  
  # datetime for scheduled time
  create_datetime "input_datetime.light_${gid}_on_time" "Время включения: $gname"
done

echo ""
echo "=== Готово ==="
echo "Проверьте в UI HA:"
echo "  - input_boolean.vlight_*"
echo "  - input_select.light_*_on"
echo "  - input_datetime.light_*_on_time"
