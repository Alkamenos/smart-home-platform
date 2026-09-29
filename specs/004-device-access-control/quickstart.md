# Quickstart: Контроль доступа к устройствам (Access Control)

**Feature**: specs/004-device-access-control | **Date**: 2026-09-29

Валидационные сценарии, доказывающие работу фичи end-to-end. Детали форматов — [contracts/access-control-api.md](contracts/access-control-api.md), структур — [data-model.md](data-model.md).

## Сценарий 1 — Unit: identification middleware и фильтрация списка (FR-001…FR-003, SC-001, SC-002)

```bash
pytest tests/contract/test_access_control.py -v
```

**Ожидаемый результат**:
- защищённый device-endpoint без `X-User-ID` → 401
- пользователь видит ровно устройства с выданным доступом; аноним → пустой список
- роль недостаточна (команда без controller) → 403; достаточна → исполнено

Дополнительно (middleware-регистрация в приложении):

```bash
pytest tests/test_webui.py -v -k "access or middleware"
```

## Сценарий 2 — Unit: grant/revoke/list — реальные данные (FR-005…FR-007, SC-004)

```bash
pytest tests/contract/test_access_control.py -v -k "grant or revoke or access_list or roles"
```

**Ожидаемый результат**:
- POST доступа → запись с реальным UUID записи (не заглушка)
- повторный grant той же паре → роль обновлена, дубликатов нет
- revoke несуществующей записи → 404; существующей → 204
- список доступов устройства → массив записей
- только admin: grant/revoke не-админом → 403; невалидная роль → 400

## Сценарий 3 — Integration: полный флоу и переживание перезапуска (FR-010, SC-004)

```bash
pytest tests/integration/test_access_control.py -v
```

**Ожидаемый результат**:
- полный флоу: выдать доступ → устройство видно → исполнить команду → отозвать → устройство скрыто
- несколько пользователей с разными ролями изолированы
- админ видит/делает всё; ограниченный пользователь — нет
- назначенный доступ переживает пересоздание приложения/сервиса (штатная персистентность)

## Сценарий 4 — Unit/Integration: WebSocket-подписка и доставка по правам (FR-008, SC-005)

```bash
pytest tests/contract/test_access_control.py -v -k websocket
pytest tests/integration/test_access_control.py -v -k websocket
```

**Ожидаемый результат**:
- подписка с доступом → `subscribed`; без доступа → `error` c device_id, подписки нет
- неаутентифицированный → `Must authenticate first` (существующее поведение)
- при доставке события проверка выполняется при каждой доставке: после отзыва доступа следующее событие не доставляется

## Сценарий 5 — Регресс всего проекта (SC-003, SC-005)

```bash
.ai/scripts/run_checks.sh
pytest tests/ --ignore=tests/contract --ignore=tests/integration -q
pytest tests/contract -q
pytest tests/integration -q
```

**Ожидаемый результат**: `run_checks.sh` exit 0 (покрытие ≥80%); относительно baseline фичи — contract/integration тесты доступа зелёные (это и есть цель фичи), остальные группы без НОВЫХ падений (сравнение с фиксацией baseline в tasks.md фичи).

## Карта сценариев → критерии

| Сценарий | SC | Статус (2026-09-29) |
|---|---|---|
| 1. Identification/фильтрация | SC-001, SC-002, SC-003, SC-005 | ✅ Пройден: contract access 11 passed + webui middleware-кейсы |
| 2. Grant/revoke/list | SC-004 | ✅ Пройден: contract access -k "grant/revoke/..." 6 passed (вкл. анти-дубликат) |
| 3. Полный флоу + перезапуск | SC-004 | ✅ Пройден: integration access 2 passed (переживание перезапуска + доставка); 3 существующих skip-маркера «Зависит от T064-T067» сохранились |
| 4. WebSocket-права | SC-005 | ✅ Пройден: T014 — подписка с доступом → доставка; после отзыва → подписка отклоняется; неаутентифицированный → «Must authenticate first» |
| 5. Регресс | SC-003, SC-005 | ✅ Пройден: run_checks exit 0 (покрытие 92.9%); root 78 failed — структура идентична baseline (новых нет); contract/integration — см. заметки tasks.md (разоблачённые pre-existing mismatches, не регрессии US4) |
