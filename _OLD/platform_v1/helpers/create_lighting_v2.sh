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
  body=$(echo "$response" | head -n-1)
  if [[ "$http_code" == "200" ]] || [[ "$http_code" == "201" ]]; then
    echo "  -> ✅ Создан"
  elif [[ "$http_code" == "409" ]]; then
    echo "  -> ⚠️  Уже существует"
  else
    echo "  -> ❌ Ошибка HTTP $http_code"
    echo "     Ответ: $body"
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
  body=$(echo "$response" | head -n-1)
  if [[ "$http_code" == "200" ]] || [[ "$http_code" == "201" ]]; then
    echo "  -> ✅ Создан"
  elif [[ "$http_code" == "409" ]]; then
    echo "  -> ⚠️  Уже существует"
  else
    echo "  -> ❌ Ошибка HTTP $http_code"
    echo "     Ответ: $body"
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
  body=$(echo "$response" | head -n-1)
  if [[ "$http_code" == "200" ]] || [[ "$http_code" == "201" ]]; then
    echo "  -> ✅ Создан"
  elif [[ "$http_code" == "409" ]]; then
    echo "  -> ⚠️  Уже существует"
  else
    echo "  -> ❌ Ошибка HTTP $http_code"
    echo "     Ответ: $body"
  fi
}

# Группы из манифеста (явный список для надёжности)
# Формат: "group_id:Group Name"
# Используем построчное чтение для максимальной совместимости
GROUPS_LIST="yard_floodlights:Улица/двор
front_door:Входная дверь
garage_gate:Ворота гаража
garden_path:Садовая дорожка
terrace:Терраса
balcony:Балкон
bedroom:Спальня
nursery:Детская
office:Кабинет
kitchen:Кухня
bathroom:Санузел
hallway:Коридор"

echo "=== Создание vlight и select+time UI для освещения ==="
echo ""

# Подсчёт количества групп
GROUP_COUNT=$(echo "$GROUPS_LIST" | wc -l)
echo "Найдено групп: $GROUP_COUNT"
echo ""

# Обработка каждой группы через while read
echo "$GROUPS_LIST" | while IFS=: read -r group_id group_name; do
  # Пропускаем пустые строки
  [ -z "$group_id" ] && continue
  
  echo "Группа: $group_id ($group_name)"
  
  # vlight toggle
  create_bool "input_boolean.vlight_${group_id}" "vlight: $group_name"
  
  # select for on-mode
  create_select "input_select.light_${group_id}_on" "Режим включения: $group_name"
  
  # datetime for scheduled time
  create_datetime "input_datetime.light_${group_id}_on_time" "Время включения: $group_name"
  create_datetime "input_datetime.light_${group_id}_off_end_time" "Конец окна выключения: $group_name"
done

echo ""
echo "=== Готово ==="
echo "Проверьте в UI HA:"
echo "  - input_boolean.vlight_*"
echo "  - input_select.light_*_on"
echo "  - input_datetime.light_*_on_time"
