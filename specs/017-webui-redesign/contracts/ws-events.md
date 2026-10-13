# Contract — WebSocket живых событий

Канал: `WS /api/v1/ws/events` (новый, унифицированный). Существующий
`WS /api/v1/ws/devices` сохраняется на время перехода и затем удаляется.

Права проверяются **при каждой доставке** сообщения (как в `/api/v1/ws/devices`), а не
только при подписке: отзыв доступа действует немедленно. Неизвестная идентичность —
fail-closed.

## Сообщения клиента → сервер

```json
{ "type": "auth", "user_id": "admin_user" }
{ "type": "subscribe", "topics": ["locations", "devices", "fsm"] }
{ "type": "subscribe", "device_id": "<uuid>" }
{ "type": "unsubscribe", "device_id": "<uuid>" }
{ "type": "ping" }
```

## Сообщения сервер → клиент

```json
{ "type": "authenticated", "user_id": "admin_user" }

{ "type": "subscribed", "topics": ["locations", "devices", "fsm"] }

{ "type": "state_change",
  "entity_id": "sensor.living_room_temperature",
  "value": 25.4, "old_value": 25.3,
  "role": "temperature", "location_id": "living_room",
  "at": "2026-10-13T18:40:00Z" }

{ "type": "fsm_transition",
  "fsm_id": "light.living_room_lighting_10",
  "device_id": "<uuid>", "state": "ON", "at": "2026-10-13T18:40:00Z" }

{ "type": "device_state",
  "device_id": "<uuid>", "status": "available", "state": {"state": "on"} }

{ "type": "pong" }
{ "type": "error", "message": "...", "device_id": "<uuid>?" }
```

## Правила доставки (проверяются тестами)

1. `state_change` уходит только подписчикам темы `locations`/`devices` и только по
   сущностям, доступным пользователю; для датчиков локаций доступ — общее наблюдение.
2. `fsm_transition` уходит подписчикам `fsm` и подписчикам соответствующего `device_id`.
3. Недоступность сервиса проверки прав → сообщение **не** отправляется (deny).
4. Обрыв соединения: клиент переподключается с экспоненциальной задержкой; при
   переподключении повторяет `auth` и подписки.
5. Поток `state_change` ограничивается темами подписки: клиент, не подписанный на
   `locations`, не получает показаний датчиков.

## Совместимость на переходный период

- Старый `/api/v1/ws/devices` работает параллельно (не ломает существующие тесты) до удаления
  старого UI.
- Формат `fsm_transition` совпадает с существующим (`fsm_id`, `state`, `timestamp`/`at`),
  чтобы логика подсветки переносилась без переписывания.
