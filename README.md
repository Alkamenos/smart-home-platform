# Smart Home Platform

Data-driven платформа умного дома поверх Home Assistant. Единый источник правды —
YAML-манифест инстанса; UI — через HA helpers; логика — pyscript (один склеенный файл).

## Структура

- `shplatform/` — CLI-валидатор и Pydantic-схема манифеста (runtime НЕ использует Pydantic)
- `shplatform/loader/registry.py` — runtime-загрузчик манифеста
- `ha/pyscript/*.py` — контроллеры (climate, ventilation, sensor_health, lighting),
  конкатенируются в один `/config/pyscript/manifest_loader.py` (порядок важен!)
- `manifests/leonid_house.yaml` — манифест инстанса
- `docs/` — SPEC, HANDOFF, правила pyscript, формат provisioning
- `tools/` — deploy.sh, smoke_light.py, gen_helpers.py

## Quickstart

```bash
source .venv/bin/activate
./tools/deploy.sh            # validate + склейка + sanity + sync манифеста + рестарт HA
./tools/deploy.sh --smoke    # после рестарта: таблица состояния освещения
python3 tools/gen_helpers.py --start-id 61   # JSON для создания недостающих helpers
```

## Документация

- `docs/SPEC.md` — контракты платформы (vlight, override, shadow)
- `docs/HANDOFF.md` — текущее состояние инстанса и roadmap (обновлять каждый сеанс!)
- `docs/PYSCRIPT_RULES.md` — ограничения pyscript, обязательны к прочтению перед правкой кода
- `docs/ENTITY_PROVISIONING.md` — формат массового создания helper-сущностей

## Текущий статус (Leonid's House)
✅ **Климат**: 4 зоны (гостиная/санузел/спальня/кабинет), shadow/real, safety (AC winter lockout, dry mode), free-heat координация
✅ **Вентиляция**: 2 рекуператора Vakio Base Smart, пресеты, boost режимы, зимняя пауза, open-doors mock
✅ **Sensor health**: детект unavailable/низкой батареи, агрегированный список покупок («Батарейка CR2450 - 2 шт»)
✅ **Освещение v2**: 12 групп, vlight-слой, select+time UI, color temp кривая (2000–6000K), backlight выключателей, имитация присутствия
✅ **Дашборд**: полный UI для управления платформой

🔜 **Следующие шаги**: кнопки управления светом, полив, реальные датчики дверей/окон, ночное окно, Яндекс диалоги

---

## 📋 Инструкция по использованию в Home Assistant

### 1. Подготовка helper-сущностей для освещения

Запустите скрипт создания helpers (требуется настроить `HA_URL` и `HA_TOKEN`):

```bash
cd /config/.platform
./helpers/create_lighting_v2.sh
```

Или создайте вручную через UI HA:
- **12 × input_boolean**: `vlight_yard_floodlights`, `vlight_front_door`, `vlight_garage_gate`, `vlight_garden_path`, `vlight_terrace`, `vlight_balcony`, `vlight_bedroom`, `vlight_nursery`, `vlight_office`, `vlight_kitchen`, `vlight_bathroom`, `vlight_hallway`
- **12 × input_select**: `light_yard_floodlights_on`, `light_front_door_on`, ... с опциями: `Не включать`, `Закат`, `Время`
- **12 × input_datetime**: `light_yard_floodlights_on_time`, `light_front_door_on_time`, ... (время включения)

### 2. Деплой платформы в Home Assistant

```bash
cd /config/.platform
./deploy.sh --ha-config /config --reload --ha-url http://homeassistant.local:8123 --token <YOUR_TOKEN>
```

Скрипт:
1. Валидирует манифест `manifests/leonid_house.yaml`
2. Склеивает 7 pyscript-файлов в `/config/pyscript/manifest_loader.py`
3. Копирует манифест в `/config/.platform/manifests/`
4. Опционально перезапускает pyscript (`--reload`)

### 3. ПОЛНЫЙ перезапуск Home Assistant

**Обязательно!** После деплоя выполните полный перезапуск HA (не только pyscript.reload):

```yaml
# Через UI: Настройки → Система → Перезапустить
# Или сервис: homeassistant.restart
```

### 4. Импорт дашборда

1. Файл дашборда уже скопирован скриптом деплоя в `/config/dashboards/smart_home.yaml`.
2. Добавьте в `configuration.yaml`:
   ```yaml
   dashboard:
     smart_home:
       mode: yaml
       title: Smart Home Platform
       filename: dashboards/smart_home.yaml
       show_in_sidebar: true
       icon: mdi:home-automation
   ```
3. Перезагрузите панель управления через UI: **Настройки** → **Панели управления** → Нажмите три точки → **Перезагрузить**.
   Или просто перезапустите HA.
4. Откройте дашборд: `http://homeassistant.local:8123/smart_home`

### 5. Управление освещением

#### Через дашборд
- **Toggle**: кнопка `vlight_<group>` — включение/выключение группы
- **Select**: выбор режима включения (`Не включать`/`Закат`/`Время`)
- **Time**: установка времени для режима `Время`

#### Через сервис (для кнопок/Алисы)
```yaml
service: pyscript.vlight_toggle
data:
  group_id: yard_floodlights  # или bedroom, office, и т.д.
```

#### Entity_id для интеграций
- Виртуальные переключатели: `input_boolean.vlight_<group_id>`
- Select режима: `input_select.light_<group_id>_on`
- Время включения: `input_datetime.light_<group_id>_on_time`

### 6. Диагностика

Сервисы для отладки:
```yaml
# Статус платформы
service: pyscript.manifest_status

# Отладка климата
service: pyscript.climate_debug

# Отладка вентиляции
service: pyscript.vent_debug

# Отладка освещения
service: pyscript.light_debug

# Sensor health
service: pyscript.sensor_health_status

# Override статус
service: pyscript.override_status
service: pyscript.light_override_clear
```

### 7. Логирование

Фильтр логов для платформы:
```
[climate] OR [ventilation] OR [sensor_health] OR [lighting] OR [manifest] OR [override]
```