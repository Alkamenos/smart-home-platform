# Исследования Phase 0: Интеграция устройств из Home Assistant

**Статус**: Завершено (восстановлено по факту кода, 2026-09-29)
**Фича**: `specs/001-device-integration`
**Основание**: plan.md → Phase 0 «Исследования и уточнения»

> Примечание: исходный файл `research.md` был заявлен в plan.md, но отсутствовал.
> Документ воссоздан по фактическому состоянию кодовой базы (коммит `834468c`).

## Вопросы спецификации → решения (8/8)

### 1. Текущая реализация HA-клиента

**Найдено**: пакет `src/adapters/home_assistant/` уже существует и содержит:
- `rest_client.py` — `HARestClient`: REST API Home Assistant (загрузка устройств, отправка команд)
- `websocket_client.py` — `HAWebSocketClient`: WebSocket-подписка на события HA + `WebSocketEventBatcher` (пакетирование в `src/core/persistence/websocket_batcher.py`)
- `connection_manager.py` — `ConnectionManager`: переподключение с exponential backoff (задержки 1, 2, 4, 8, 16 сек, не более `max_retry_delay`)

**Решение**: использовать существующий пакет; новые компоненты не требуются, интеграция идёт через `DeviceService`.

### 2. Модели данных HA

**Найдено**: `src/adapters/home_assistant/` использует Pydantic-модели сущностей HA; доменные модели вынесены в `src/core/models/`:
`Device`, `DeviceConfig`, `DeviceCommand`, `DeviceAccess`, `HASource`.

**Решение**: модель данных spec (HASource / Device / DeviceConfig / DeviceCommand) реализована в `src/core/models/`; валидация манифеста — `src/core/manifest_validator.py`.

### 3. Персистентность конфигурации

**Найдено**:
- Источники хранятся в `data/sources.json` через `src/core/persistence/sources.py` (миграции — `src/core/persistence/migrations/001_init_sources.py`)
- Состояние устройств — `DeviceCache` (`src/core/persistence/cache.py`) с индексацией (`index_manager.py`), JSON-based (совместимо с конституцией)

**Решение**: JSON-based persistence подтверждён как в plan.md (принцип «Manifest as Config» соблюдён).

### 4. EventBus для событий синхронизации

**Найдено**: `src/core/events/event_bus.py` (`EventBus`) подключён к `DeviceService`:
публикация событий загрузки устройства, изменения конфигурации, изменения состояния, команды и изменения доступа (`device_service.py:442, 486, 763, 1008, 1047`).

**Решение**: события идут через EventBus (Принцип I конституции). Отдельная модель `DeviceSyncEvent` с before/after **не реализована** — это Known Issue / Technical Debt (ТР-010, H1 из анализа).

### 5. WebSocket в проекте

**Найдено**: уже два уровня WebSocket:
1. **Внутренний** (браузер ↔ платформа): `src/webui/routes/devices/websocket.py` → `/api/v1/ws/devices` (auth/subscribe/state_changed/ping-pong, проверка доступа T071)
2. **Внешний** (платформа ↔ HA): `HAWebSocketClient` + батчер

**Решение**: архитектура «HA WebSocket → EventBus → WebUI WebSocket» реализована; полнота тестов reconnect — Known Issue #5 (H5 анализа).

### 6. Хранение токенов и безопасность

**Найдено**:
- `src/core/security/encryption.py` — `TokenEncryptor`: токен шифруется при записи и расшифровывается при чтении (`persistence/sources.py:51, 83`)
- `src/core/secrets.py` — `SecretsResolver`: резолв `${HA_TOKEN}` из переменных окружения + `validate_no_plain_secrets()` для манифестов
- Валидация токена в API: `CreateSourceRequest.token: min_length=10`

**Решение**: требование «токены хранятся зашифрованными» (spec, допущения) выполнено. Способ передачи — env/`${SECRET}`, plaintext в манифесте запрещён.

### 7. Идентификация и дедупликация устройств

**Найдено**: устройства идентифицируются по `ha_entity_id` (unique), отображение — `display_name` (spec, «Дедупликация»). Уникальность `display_name` в пределах источника **на уровне API не валидируется** — правило data-model.md отложено (бэклог RU T035, анализ H3).

**Решение**: дедупликация по `ha_entity_id` — рабочий механизм; правило уникальности display_name — задокументированное отложение.

### 8. Миграция состояния устройств при недоступности HA

**Найдено**: статус `removed_from_ha` для устройств, исчезнувших из HA (spec, граничные случаи); статусная модель `Device.status` в `src/core/models/device.py`.

**Решение**: стратегия «оставить с пометкой, ручное удаление/переподключение» реализуема и соответствует спецификации; ручное удаление — REST `DELETE`-семантика через UI (см. contracts/rest-api.md).

## Рекомендации для проектирования

1. Новые модули не нужны — интеграция идёт через существующие `HARestClient`/`HAWebSocketClient`/`ConnectionManager`/`DeviceService`
2. Дальнейшая работа — закрытие бэклога tasks.md (42 задачи): access control (H2), DeviceSyncEvent (H1), reconnect-тесты (H5)
3. Контракты API зафиксированы в `contracts/rest-api.md` (фактические пути `/api/v1/...`)
