# Диагностика проблемы: "Ошибка при загрузке данных из Home Assistant"

## 🔍 Основные причины ошибки

### 1. **Отсутствует parameter `source_id` в URL** ⚠️ (САМАЯ ЧАСТАЯ)

Убедитесь, что вы открываете страницу с правильным URL:

```
❌ НЕПРАВИЛЬНО:
http://localhost:8000/discovery

✅ ПРАВИЛЬНО:
http://localhost:8000/discovery?source_id=550e8400-e29b-41d4-a716-446655440000
```

### 2. **Источник не существует**

Если вы видите ошибку `Источник ... не найден`, значит нужно сначала создать источник:

```bash
# 1. Создайте источник через API
curl -X POST http://localhost:8000/api/v1/devices/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Home Assistant",
    "url": "http://homeassistant.local:8123",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  }'

# 2. Сохраните полученный source_id

# 3. Откройте страницу с этим source_id
http://localhost:8000/discovery?source_id=ПОЛУЧЕННЫЙ_UUID
```

### 3. **Неправильные учетные данные Home Assistant**

Если вы видите `Не удалось подключиться к Home Assistant`, проверьте:

- ✅ URL Home Assistant доступен и работает
- ✅ Токен корректный (Long-lived access token)
- ✅ Нет проблем с сетью между приложением и HA

```bash
# Проверьте подключение вручную
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://homeassistant.local:8123/api/

# Должен вернуться 200 OK и версия HA
```

---

## 📊 Как диагностировать проблему

### Шаг 1: Откройте консоль браузера
- Нажмите **F12** → вкладка **Console**
- Посмотрите на сообщения об ошибках

### Шаг 2: Проверьте NetworkTab
- Нажмите **F12** → вкладка **Network**
- Обновите страницу (F5)
- Найдите запрос к `discovery-data`
- Проверьте Status Code:
  - `404` → Источник не найден
  - `503` → Ошибка подключения к HA
  - `500` → Ошибка на сервере

### Шаг 3: Логи сервера
```bash
# Посмотрите логи FastAPI приложения
# Ищите сообщения вроде:
# "Источник ... не найден"
# "Подключаюсь к HA: ..."
# "Не удалось подключиться к Home Assistant"
```

---

## ✅ Полный workflow

```
1. Создать источник (если его еще нет)
   ↓
2. Копировать source_id
   ↓
3. Открыть страницу: /discovery?source_id=YOUR_UUID
   ↓
4. Система загружает комнаты из HA
   ↓
5. Выбираете устройства
   ↓
6. Нажимаете "Применить"
```

---

## 🐛 Пример создания источника через terminal

```bash
# Сохраните это в файл create_source.sh

SOURCE_URL="http://homeassistant.local:8123"
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
NAME="My Home Assistant"

curl -X POST http://localhost:8000/api/v1/devices/sources \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"$NAME\",
    \"url\": \"$SOURCE_URL\",
    \"token\": \"$TOKEN\"
  }" | jq .

# Результат:
# {
#   "id": "550e8400-e29b-41d4-a716-446655440000",
#   "name": "My Home Assistant",
#   "url": "http://homeassistant.local:8123",
#   ...
# }

# Теперь откройте:
# http://localhost:8000/discovery?source_id=550e8400-e29b-41d4-a716-446655440000
```

---

## 🔐 Где взять Long-lived access token из Home Assistant

1. Откройте Home Assistant
2. Нажмите на иконку профиля (右нижний угол)
3. Прокрутите вниз до "Long-Lived Access Tokens"
4. Нажмите "Create Token"
5. Дайте ему имя (например, "Smart Home Platform")
6. Скопируйте сгенерированный токен

---

## 📞 Если проблема не решена

1. Проверьте файл `DEVICE_DISCOVERY_COMPLETION.md` для полной документации
2. Посмотрите логи консоли браузера (F12 → Console)
3. Проверьте логи сервера на предмет сообщений об ошибках
4. Убедитесь, что Home Assistant доступен из сети приложения
