# Contract — HTTP API (фронтенд ↔ платформа)

Все запросы идут с того же origin. Идентичность — заголовки `X-User-ID` и
`X-Is-Admin` (существующая модель доступа, не меняется). Ошибки не смешиваются:
`401` — нет идентичности, `403` — прав недостаточно, `404` — объекта нет, `503` —
платформа/сервис недоступен. Пустой результат — `200` с пустым списком, а не `503`.

## Новые endpoint'ы (добавляются этим планом)

### `GET /api/v1/session`

Bootstrap идентичности вместо серверных атрибутов `<body>`.

```json
{ "user_id": "admin_user", "is_admin": true, "display_name": "Инженер" }
```

### `GET /api/v1/overview`

Агрегат для раздела «Дом»: локации со снимками, устройства, состояния автоматов, тревоги.
Права: устройства — по доступу пользователя; локации — агрегированное наблюдение.

```json
{
  "generated_at": "2026-10-13T18:40:00Z",
  "locations": [
    {
      "id": "living_room", "name": "Гостиная", "kind": "room", "status": "ok",
      "readings": [
        {"role": "temperature", "entity_id": "sensor.t", "value": 25.35,
         "unit": "°C", "at": "...", "stale": false, "unavailable": false}
      ],
      "derived": {"presence": true, "last_motion": "...", "open_windows": 0,
                  "sensors_available": 5, "sensors_stale": 0}
    }
  ],
  "devices": [ /* как DeviceResponse: id, name, ha_entity_id, device_type,
                  status, actual state, fsm[], behaviors[], automation */ ],
  "alerts": [
    {"kind": "stale_sensor", "subject": "sensor.soil_1", "severity": "info",
     "detail": "Датчик почвы молчит с 9 октября", "at": "..."}
  ]
}
```

### `GET /api/v1/events`

Журнал с фильтрами и курсорной пагинацией (для «Журнала» и деталей).

Query: `device`, `location`, `level`, `trace`, `from`, `to`, `limit`, `cursor`.
Ответ: `{ "records": [...], "next_cursor": "..." | null }`, каждая запись — как
`JournalEvent` из data-model.

## Существующие endpoint'ы (переиспользуются без изменения контракта)

| Endpoint | Назначение в новом UI |
|---|---|
| `GET /api/v1/locations` | Список локаций (детали, навигация) |
| `GET /api/v1/locations/{id}/state` | Снимок локации (страница локации) |
| `GET /api/v1/locations/{id}/history` | Динамика показаний |
| `GET /api/v1/devices` | Список устройств («Автоматика») |
| `GET /api/v1/devices/{id}` | Устройство |
| `POST /api/v1/devices/{id}/command` | Управление прибором |
| `GET /api/v1/devices/{id}/command/{command_id}` | Статус команды |
| `GET /api/v1/devices/{id}/events` | История устройства |
| `PUT /api/v1/devices/{id}/config` | Правка конфигурации устройства |
| `PUT /api/v1/devices/{id}/behaviors` | Поведения и параметры |
| `POST /api/v1/devices/apply` | Импорт устройств из источника |
| `…/access`, `…/access/{id}` (GET/POST/DELETE) | Права доступа к устройству |
| `GET/POST/DELETE /api/v1/devices/sources/…` | Источники, `sync`, `discovery-data`, `from-env` |
| `GET /api/fsm/state` | Состояния автоматов |
| `GET /api/fsm/{entity_id}/diagram` | Mermaid-схема автомата |
| `GET /health`, `GET /ready`, `GET /metrics` | Раздел «Система» |

## Требуемая правка раздачи

FastAPI дополняется раздачей `frontend/out` на `/` с SPA-фолбэком на `index.html` для
неизвестных не-API путей. Порядок регистрации: API/служебные маршруты — раньше статики.
Зарезервированные пути, под которые **не** создаются страницы SPA:
`/api/**`, `/health`, `/ready`, `/metrics`, `/api/v1/ws/**`.

## Коды и семантика (проверяется в тестах)

- Устройства в `overview` фильтруются по доступу; локации — нет (агрегированное наблюдение).
- `503` для `overview` — только если движок/сервис недоступен; «нет данных» — `200` с пустыми
  списками.
- Команда возвращает `automation_synced`, по которому UI отличает «автоматика учла» от
  «команда ушла напрямую».
