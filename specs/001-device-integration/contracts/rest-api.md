# REST API контракты: Устройства Home Assistant

**Статус**: Завершено (восстановлено по факту кода, 2026-09-29)
**Фича**: `specs/001-device-integration`
**Источник истины**: `src/webui/routes/devices/` (devices.py, sources.py, access_control.py, websocket.py)

> Примечание: исходный `contracts/rest-api.md` был заявлен в plan.md, но отсутствовал.
> Документ описывает **фактически реализованные** маршруты. Пути плана `/api/devices/*`
> устарели — актуальный префикс **`/api/v1/*`** (H4 анализа).

## Общие правила

- Базовый префикс: `/api/v1`
- Формат обмена: JSON (`Content-Type: application/json`)
- Идентификаторы: UUID
- Аутентификация платформы: заголовок `X-User-ID: <uuid>` (адаптация под ролевой доступ — бэклог, H2)
- Токен HA никогда не возвращается в ответах API (расшифровка только при чтении из хранилища)

---

## 1. Источники Home Assistant

Префикс: `/api/v1/devices/sources` · Модуль: `src/webui/routes/devices/sources.py`

### `POST /api/v1/devices/sources` — создать источник

```json
// Request
{ "name": "Home Assistant Test", "url": "http://192.168.1.100:8123", "token": "..." }
// 201 Created
{ "id": "uuid", "name": "...", "url": "...", "status": "...", "last_sync": null, "created_at": "..." }
```

Валидация: `token` — минимум 10 символов (`CreateSourceRequest`). 422 — при нарушении Pydantic-схемы.

### `GET /api/v1/devices/sources` → `200` список `SourceResponse`
### `GET /api/v1/devices/sources/{source_id}` → `200` | `404`
### `DELETE /api/v1/devices/sources/{source_id}` → `204`
### `POST /api/v1/devices/sources/{source_id}/sync` → `200` — запуск синхронизации из HA
### `GET /api/v1/devices/sources/{source_id}/discovery-data` → `200` — кандидаты для добавления в манифест

---

## 2. Устройства

Префикс: `/api/v1/devices` · Модуль: `src/webui/routes/devices/devices.py`

| Метод | Путь | Успех | Назначение |
|-------|------|-------|-----------|
| GET | `/api/v1/devices` | 200 | Список устройств |
| GET | `/api/v1/devices/{device_id}` | 200 \| 404 | Полная информация об устройстве |
| PUT | `/api/v1/devices/{device_id}/config` | 200 \| 404 \| 422 | Обновление конфигурации |
| POST | `/api/v1/devices/{device_id}/command` | 202 \| 404 \| 500 | Отправка команды в HA |
| GET | `/api/v1/devices/{device_id}/command/{command_id}` | 200 \| 404 | Статус выполнения команды |
| GET | `/api/v1/devices/{device_id}/events` | 200 \| 404 | История операций |
| POST | `/api/v1/devices/apply` | 201 \| 400 \| 500 | Применение устройств в манифест |

### `PUT /api/v1/devices/{device_id}/config` (ТР-004)

```json
// UpdateDeviceConfigRequest (частичное обновление)
{ "display_name": "Свет гостиная", "description": "...", "location": "living_room", "tags": ["основной"] }
```

Границы (по docstring `update_device_config`): `display_name` 1–255 символов, `description` ≤1000, `location` ≤255, `tags` ≤10 шт. по ≤50 символов.
⚠ **Уникальность `display_name` в пределах источника заявлена в docstring, но не валидируется кодом** (отложено — бэклог RU T035, анализ H3).

### `POST /api/v1/devices/{device_id}/command` (ТР-007)

`202 Accepted` — команда поставлена в очередь отправки в HA; `500` — ошибка отправки (см. граничные случаи spec: «устройство недоступно»).

---

## 3. Управление доступом (ТР-009)

Префикс: `/api/v1/devices` · Модуль: `src/webui/routes/devices/access_control.py`

| Метод | Путь | Успех | Назначение |
|-------|------|-------|-----------|
| POST | `/{device_id}/access` | 201 | Назначить доступ пользователю/роли |
| GET | `/{device_id}/access` | 200 | Список прав устройства |
| DELETE | `/{device_id}/access/{access_id}` | 204 | Отозвать доступ |

⚠ Маршруты реализованы, но **единый middleware-фильтр не подключён** — сценарий US4.2 (403 для пользователя без прав) сейчас не гарантирован (Known Issue #11, бэклог RU T067–T071).

---

## 4. WebSocket (ТР-006)

`ws://.../api/v1/ws/devices` · Модуль: `src/webui/routes/devices/websocket.py`

| Направление | Сообщение | Описание |
|---|---|---|
| клиент → сервер | `{"type":"auth","user_id":"uuid"}` | Авторизация (обязательна перед подпиской) |
| клиент → сервер | `{"type":"subscribe","device_id":"uuid"}` | Подписка на устройство (проверка доступа, T071) |
| клиент → сервер | `{"type":"unsubscribe","device_id":"uuid"}` | Отписка |
| клиент → сервер | `{"type":"ping"}` | Heartbeat |
| сервер → клиент | `{"type":"authenticated"/"subscribed"/"unsubscribed"/"pong"}` | Подтверждения |
| сервер → клиент | `{"type":"state_changed","device_id":"...","state":{...}}` | Изменение состояния ≤5 сек (КУ-004) |
| сервер → клиент | `{"type":"error","message":"..."}` | Ошибка |

---

## Известные замечания реализации (по фактам кода)

1. **Дублирование регистрации маршрутов** (`devices.py`):
   - `POST /apply` — зарегистрирован дважды (:46 поверх `get_devices` и :474 `apply_devices`)
   - `POST /{device_id}/command` — зарегистрирован дважды (:228 `send_device_command`, :290 `execute_device_command`)
   FastAPI матчтит по порядку регистрации → фактически отвечают первые обёртки. Требует рефакторинга (бэклог).
2. **`DeviceSyncEvent` (before/after)** — эндпоинт `GET .../events` есть, но модель событий с before/after не реализована (ТР-010, H1).
3. **КУ-006 (переподключение ≤30 сек)** — `ConnectionManager` использует exponential backoff, интеграционных тестов reconnect нет (Known Issue #5, H5).
