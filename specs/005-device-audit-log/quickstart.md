# Quickstart: История операций с устройствами (ТР-010)

**Date**: 2026-09-29 | **Spec**: [spec.md](./spec.md) | **Contract**: [contracts/device-events-api.md](./contracts/device-events-api.md)

Валидационные сценарии прогоняются после реализации (Phase 3 tasks). Предпосылки: платформа запущена, устройство существует, есть пользователи с ролями (как в quickstart spec 004).

## Сценарий 1 — История конфигурации (SC-001, FR-001, FR-003)

1. Авторизованный администратор: `PUT /api/v1/devices/{id}/config` с `{"location": "гостиная"}`
2. `GET /api/v1/devices/{id}/events?event_type=config_changed`
3. **Успех**: массив содержит запись `event_type=config_changed` с `data.user_id` идентификатором инициатора, `data.before`/`data.after` с изменённым полем

## Сценарий 2 — История прав доступа (SC-002, FR-004)

1. Администратор: `POST /api/v1/devices/{id}/access` (выдача), затем отзыв
2. `GET /api/v1/devices/{id}/events?event_type=access_granted` и `?event_type=access_revoked`
3. **Успех**: обе операции присутствуют; в записях — получатель права и инициатор; у выдачи `after` содержит роль

## Сценарий 3 — История команд (SC-001, FR-005, clarify Q1)

1. Пользователь с ролью controller: `POST /api/v1/devices/{id}/command`
2. `GET /api/v1/devices/{id}/events?event_type=command_executed`
3. **Успех**: запись содержит инициатора и содержимое команды в `data`; `before`/`after` пустые

## Сценарий 4 — Переживание перезапуска (SC-003, FR-002)

1. Выполнить операции из сценариев 1–3
2. Пересоздать приложение (рестарт контейнера / пересоздание `PersistenceManager` на том же `data_dir`)
3. `GET /api/v1/devices/{id}/events`
4. **Успех**: все записи доступны, порядок — новые первыми

## Сценарий 5 — Фильтр, пагинация, отказы (FR-007, FR-008, contract-кейсы)

1. `GET .../events?event_type=config_changed` → только операции конфигурации; `?event_type=nonexistent` → `[]`
2. `GET .../events?limit=1&offset=1` → вторая запись списка
3. Без заголовков идентификации → 401; без роли viewer → 403; неизвестный device → 404
4. **Успех**: контрактные кейсы 1–9 из `contracts/device-events-api.md` выполнены

## Сценарий 6 — Ошибка записи не блокирует (FR-009)

1. Затруднить запись истории (недоступный `data_dir` / отсутствующий persistence в state)
2. Выполнить `PUT .../config`
3. **Успех**: операция возвращает 200 (конфигурация изменена), в логе — ошибка записи истории, ответ не упал

## Карта сценариев → критерии

| Сценарий | SC / FR | Тестовый уровень | Статус (2026-09-30) |
|---|---|---|---|
| 1. Конфигурация | SC-001, FR-001, FR-003 | contract + integration | ✅ Пройден: `test_config_update_creates_history_record` + contract «recorded/filter» |
| 2. Права доступа | SC-002, FR-004 | integration | ✅ Пройден: `test_grant_update_and_revoke_recorded` (granted/updated/revoked) |
| 3. Команды | SC-001, FR-005 | contract + integration | ✅ Пройден: `test_command_creates_history_record` (до/после пустые — clarify Q1) |
| 4. Перезапуск | SC-003, FR-002 | integration | ✅ Пройден: `test_records_survive_app_restart` (create_app на том же data_dir) |
| 5. Фильтр/отказы | FR-007, FR-008 | contract | ✅ Пройден: 8/8 контрактных кейсов (1–3, 5–9) |
| 6. Отказ записи | FR-009, SC-005 | unit + integration | ✅ Пройден: `test_config_update_success_even_if_history_unavailable` (persistence=None → 200) |

## Команды проверки качества

```bash
# Тесты фичи
pytest tests/unit/test_device_sync_event.py tests/unit/test_device_sync_persistence.py \
       tests/contract/test_device_events_api.py tests/integration/test_device_audit_log.py

# Полные проверки перед коммитом
.ai/scripts/run_checks.sh
```
