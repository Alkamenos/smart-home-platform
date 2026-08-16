# Формат provisioning helper-сущностей

Массовое создание helpers идёт внешним инструментом, принимающим JSON:

```json
[
  {"id": 1, "type": "input_boolean/create", "name": "vlight_yard_floodlights", "icon": "mdi:lightbulb"},
  {"id": 13, "type": "input_select/create", "name": "light_yard_floodlights_on",
   "options": ["Не включать", "Закат", "Время"], "initial": "Закат", "icon": "mdi:form-select"},
  {"id": 25, "type": "input_datetime/create", "name": "light_yard_floodlights_on_time",
   "has_date": false, "has_time": true, "icon": "mdi:clock-outline"}
]
```

## Конвенция имён (строго!)

Для каждой группы освещения с `id` из манифеста создаётся тройка:
- `input_boolean.vlight_<id>` — командная шина (UI/Алиса/кнопки)
- `input_select.light_<id>_on` — опции СТРОГО `["Не включать", "Закат", "Время"]`
  (контроллер сравнивает строки; `initial` = `Закат`)
- `input_datetime.light_<id>_on_time` — только время (`has_date: false, has_time: true`)

Генератор: `python3 tools/gen_helpers.py --start-id N [--groups a,b]`.
Автогенерация дашборда в будущем должна читать тот же манифест.
