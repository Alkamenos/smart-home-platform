#!/bin/bash
# Скрипт создания helper-сущностей для lighting v2 (vlight + select+time UI)

# Функция создания input_boolean
create_bool() {
  local entity="$1"
  local name="$2"
  echo "Creating $entity ($name)"
  curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" -d "{\"name\": \"$name\"}" \
    "$HA_URL/api/services/input_boolean/add" 2>/dev/null || echo "  -> exists or error"
}

# Функция создания input_select
create_select() {
  local entity="$1"
  local name="$2"
  echo "Creating $entity ($name)"
  curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$name\", \"options\": [\"Не включать\", \"Закат\", \"Время\"]}" \
    "$HA_URL/api/services/input_select/add" 2>/dev/null || echo "  -> exists or error"
}

# Функция создания input_datetime
create_datetime() {
  local entity="$1"
  local name="$2"
  echo "Creating $entity ($name)"
  curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$name\", \"has_date\": true, \"has_time\": true}" \
    "$HA_URL/api/services/input_datetime/add" 2>/dev/null || echo "  -> exists or error"
}

# Группы из манифеста
GROUPS=(
  "yard_floodlights:Улица/двор"
  "street_night:Уличное ночное"
  "office:Кабинет"
  "bedroom:Спальня"
  "kitchen_work:Кухня рабочая"
  "table:Обеденный стол"
  "container:Контейнер"
  "bathroom:Санузел"
  "garland_terrace:Гирлянда терраса"
  "garland_street:Гирлянда уличная"
  "garland_windows:Гирлянда окна"
  "xmas_a2:Рождественская A2"
)

echo "=== Создание vlight и select+time UI для освещения ==="

for group_entry in "${GROUPS[@]}"; do
  gid="${group_entry%%:*}"
  gname="${group_entry##*:}"
  
  # vlight toggle
  create_bool "input_boolean.vlight_${gid}" "vlight: $gname"
  
  # select for on-mode
  create_select "input_select.light_${gid}_on" "Режим включения: $gname"
  
  # datetime for scheduled time
  create_datetime "input_datetime.light_${gid}_on_time" "Время включения: $gname"
done

echo "=== Готово ==="
