# Data Model: Состояние локации

**Feature**: 016-location-state · **Дата**: 2026-10-13 · **Статус**: Draft

Источники: `research.md` этой спеки, ответы владельца 2026-10-13, разбор кода
(`event_router.py`, `state_snapshot.py`, `event_store.py`, `fsm_state_bridge.py`,
`tools/ha_areas_dump.py`, `specs/008-fsm-observability/`).

---

## 1. Локация

Локация — именованная область наблюдения. Виды: **комната** (уже есть в манифесте),
**улица**, **сад/грядки** (новые, задаются вручную).

### 1.1. Комнаты

Комната манифеста **уже является локацией**: её датчики лежат в
`RoomConfig.sensors` (роль → сущность HA), см. `src/core/models/manifest.py:48-68`.
Отдельно описывать комнаты в новом разделе не нужно — они попадают в набор локаций
автоматически (`kind: room`).

### 1.2. Особые зоны (новый раздел манифеста)

```yaml
locations:
  - id: ulitsa
    name: Улица
    kind: outdoor
    sensors:
      temperature: sensor.temperatura_na_ulitse_srednee
      humidity: sensor.vlazhnost_ulitsa
      illuminance: sensor.osveshchennost_ulitsa
      rain: binary_sensor.dozhd
      wind_speed: sensor.veter_skorost
  - id: gryadki
    name: Грядки
    kind: garden
    sensors:
      soil_moisture: sensor.pochva_vlazhnost_1
      soil_temperature: sensor.pochva_temperatura_1
      soil_ph: sensor.pochva_ph_1
```

- `id` — уникален среди локаций и комнат; `name` — человекочитаемое;
  `kind` — `room | outdoor | garden | other` (влияет только на оформление и
  умолчания, не на логику);
- `sensors` — явная привязка роль → `entity_id` (FR-010), без угадывания по именам.

Манифест версионируется (`.ai/04_RULES.md:221-225`): добавление `locations`
секции — не ломающее (по умолчанию пусто), `version` повышать только при
несовместимости.

## 2. Роли датчиков

Роль задаёт смысл показания и то, как оно попадает в снимок. Сегодня в
`SENSOR_EVENT_MAP` (`event_router.py:80-86`) есть только `motion`, `temperature`,
`humidity`, `lux`, `contact`. Ниже — целевой набор; часть ролей уже поддержана,
часть добавляется.

| Роль | Тип | Единица | Пример | Примечание |
|------|-----|---------|--------|-----------|
| `temperature` | число | °C | комнатная/уличная температура | есть |
| `humidity` | число | % | влажность | есть |
| `illuminance` | число | lx | освещённость (алиас `lux`) | есть как `lux`; ввести `illuminance` и оставить `lux` алиасом |
| `motion` | булево | — | присутствие/движение | есть |
| `contact` | булево | — | окно/дверь открыт(о) | есть (не используется в бою) |
| `pressure` | число | hPa | атмосферное давление | новое |
| `wind_speed` | число | м/с | скорость ветра | новое |
| `wind_gust` | число | м/с | порыв | новое |
| `rain` | булево/число | — / мм | дождь | новое |
| `uv_index` | число | — | УФ | новое |
| `co2` | число | ppm | CO₂ в комнате | новое |
| `soil_moisture` | число | % | влажность почвы | новое |
| `soil_temperature` | число | °C | температура почвы | новое |
| `soil_ph` | число | pH | кислотность | новое |
| `soil_ec` | число | µS/см | проводимость (питание) | новое |
| `battery` | число | % | заряд датчика | служебная, в снимок как признак |

Правило: роль из манифеста должна быть известна маршрутизатору (иначе датчик не
получит событий — `event_router.py:133`). Новые роли добавляются в
`SENSOR_EVENT_MAP` с типом события (`*_changed`) и в подписку HA
(`collect_subscribed_entities`).

## 3. Снимок локации

Единая структура, отдаваемая по HTTP и зеркалируемая в HA.

```json
{
  "location": {"id": "spalnia", "name": "Спальня", "kind": "room"},
  "at": "2026-10-13T06:12:03",
  "available": true,
  "readings": {
    "temperature": [{"value": 22.4, "unit": "°C", "at": "2026-10-13T06:11:50", "stale": false, "available": true}],
    "motion":      [{"value": "on", "unit": null, "at": "2026-10-13T06:09:12", "stale": false, "available": true}],
    "contact":     [{"value": "off", "unit": null, "at": "2026-10-12T22:40:00", "stale": false, "available": true}]
  },
  "derived": {
    "occupied": true,
    "last_motion_at": "2026-10-13T06:09:12",
    "last_motion_ago_sec": 171,
    "contacts_open": ["binary_sensor.okno_spalnia"],
    "stale_count": 0,
    "stale_sensors": [],
    "available_count": 3,
    "sensor_count": 3
  }
}
```

- `readings.<role>` — **список**: у одной роли бывает несколько датчиков
  (две температуры). Один датчик — список из одного элемента.
- `at` — время последнего показания датчика; `stale` — прошло больше порога
  молчания; `available` — состояние не `unavailable/unknown`.
- `value` — число или строка (`on/off`); единица берётся из атрибутов HA
  (`unit_of_measurement`) один раз при привязке.
- `derived` — вычисляется на чтение из сохранённых показаний (не хранится):

| Производная | Смысл | Правило |
|-------------|-------|---------|
| `occupied` | человек в локации | есть `motion=on` не старше `presence_window_sec` |
| `last_motion_at` / `last_motion_ago_sec` | последнее движение | по последнему `motion`, где было `on` |
| `contacts_open` | открытые проёмы | все `contact=on` |
| `stale_count` / `stale_sensors` | молчащие датчики | `now - reading.at > stale_after_sec` |
| `available_count` / `sensor_count` | доступность | сколько датчиков отвечают |

Пороги (`presence_window_sec`, `stale_after_sec`) — параметры дома, а не константы
кода; значения по умолчанию: присутствие — 10 минут, молчание — по типу датчика
(для батарейных — сутки).

## 4. Журнал изменений

- Источник: изменения показателей локации (события `state_change` из шины,
  которые уже публикует `ha_adapter.py:1412-1437`).
- Хранилище: **существующий `EventStore`** (SQLite `history.db`,
  `src/core/persistence/event_store.py`), где уже есть таблица `events` с
  `timestamp`, `entity_id`, значением; дополняется привязкой к **локации и роли**
  (новая колонка/таблица-проекция). Ретенция — как сейчас, 30 дней
  (`cleanup_old_data`).
- Запись делается **только при фактическом изменении значения** (FR-006, edge
  case про дребезг): повтор того же значения не пишется.
- Запрос истории — по локации и интервалу (см. §6).

Альтернатива (отложить): периодические срезы снимка. Владелец выбрал «журнал
изменений», поэтому срезы — отдельная задача.

## 5. Зеркало в Home Assistant (MQTT-автообнаружение)

MQTT в доме есть (проверено: сервис `mqtt.publish` доступен). Платформа **не
создаёт сущности** — она публикует конфигурацию обнаружения и значения, а HA
создаёт сущности сам.

Топики (префикс `behavioral` — параметр дома):

| Топик | Публикация | Назначение |
|-------|-----------|-----------|
| `homeassistant/sensor/behavioral_<loc>_<role>/config` | retain | обнаружение по показателю |
| `homeassistant/sensor/behavioral_<loc>/config` | retain | обнаружение сводной сущности локации |
| `behavioral/location/<loc>/<role>/state` | retain | значение показателя |
| `behavioral/location/<loc>/<role>/attributes` | retain | JSON: `{value, unit, at, stale, available}` |
| `behavioral/location/<loc>/state` | retain | сводка: число доступных датчиков |
| `behavioral/location/<loc>/attributes` | retain | JSON: полный снимок (`readings` + `derived`) |

- По показателям создаются обычные `sensor.*` (для графиков и автоматизаций);
  сводная сущность `sensor.behavioral_<loc>` несёт **полный снимок в атрибутах**
  (`json_attributes_topic`) — её и читает анализ/ИИ.
- Все публикации `retain=true`: после перезапуска HA сущности восстанавливаются
  без ожидания события (FR-008, сценарий 2).
- Публикация — через HA-сервис `mqtt.publish` (тот же путь `call_service`, что и
  команды), домен `core`, вызов через адаптер (слойность: `core` не импортирует
  `adapters`, `.ai/04_RULES.md:194-212`).
- Недоступность MQTT не влияет на снимок и журнал; отказ пишется в журнал (FR-009).

## 6. HTTP API

| Метод и путь | Ответ |
|--------------|-------|
| `GET /api/v1/locations` | список локаций (id, name, kind, число датчиков) |
| `GET /api/v1/locations/{id}/state` | снимок (§3) |
| `GET /api/v1/locations/{id}/history?from=&to=` | записи журнала за интервал |

Рядом с существующими эндпоинтами (`/api/fsm/state`, `/api/events/history`,
`src/webui/routes/__init__.py`). Права — как у устройств (`X-User-ID`, при
необходимости `X-Is-Admin`).

## 7. Где живёт код (набросок, не финальный план)

- `core/models/location.py` — `Location`, `SensorBinding`, `Reading`, `LocationSnapshot`.
- `core/services/location_state.py` — сбор и обновление снимков, производные.
- `core/persistence/event_store.py` — привязка записей к локации/роли (расширение).
- `core/services/location_mirror.py` — публикация в MQTT через интерфейс адаптера.
- `webui/routes/locations.py` — HTTP-эндпоинты.
- Манифест: `Manifest.locations`, роли в `SENSOR_EVENT_MAP`, пороги в
  `automation_rules`.

## 8. Открытые вопросы (решить на этапе плана)

1. **Порог молчания** по типам датчиков (батарейные — сутки, сетевые — час?) —
   параметр дома или умолчание по роли.
2. **Агрегат по нескольким датчикам одной роли** (две температуры): среднее,
   максимум или «оба» в аналитику.
3. **Единицы**: брать из HA (`unit_of_measurement`) или задавать в манифесте.
4. **Ретенция журнала локаций** — оставить 30 дней как у событий или отдельный срок.
5. **История датчиков, которых нет в манифесте** — фича покрывает только
   привязанные датчики (FR-010); остальное — вне объёма.
6. **Периодические срезы** (даже если владелец выбрал журнал изменений) — отдельная
   задача, если для анализа понадобятся регулярные отметки.
