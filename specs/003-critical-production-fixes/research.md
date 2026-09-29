# Phase 0 Research: Критические продакшен-фиксы (Phase 9.8)

**Статус**: Завершено | **Дата**: 2026-09-29
**Основание**: plan.md → Technical Context, все unknowns спецификации закрыты

## R1. Модуль healthcheck контейнера: где и какой

**Наблюдение**: `deploy/docker/docker-compose.prod.yml` уже объявляет
`healthcheck.test: ["CMD", "python", "-m", "src.cli.health_check"]`, но файла
`src/cli/health_check.py` не существует (`src/cli/` содержит только `commands/`).
Compose считает контейнер unhealthy после 3 неудач за 30с интервалом (start_period 40с).

**Decision**: создать `src/cli/health_check.py` с точным именем, на которое ссылается compose.

**Rationale**: compose — источник истины (менять его = менять деплой-контракт); enhancement 20 предполагал проверку через curl, но фактическая конфигурация compose уже выбрали CLI-модуль.

**Альтернативы**:
- Переписать healthcheck в compose на `curl localhost:8125/health` — отклонено: ломает уже заданный контракт, требует curl в образе (он есть, но второй источник истины)
- Импорт-проверка (import app) — отклонено: не проверяет, что сервер реально слушает

**Механика**: модуль выполняет HTTP-пробу `http://127.0.0.1:{WEBUI_PORT|8125}/health` с таймаутом ≤5с; exit 0 при 200, exit 1 при недоступности/не-200. Порт из ENV `WEBUI_PORT` (дефолт 8125, как в `src/main.py`).

## R2. Что считать «готовностью» (/health)

**Наблюдение**: `/health` в `src/webui/routes/__init__.py:37` возвращает **HTML** 200. Метрики-сервер (`src/services/metrics_server.py:96`) имеет свой `_handle_health`. Healthcheck-контракт должен быть машиночитаемым.

**Decision**: `/health` возвращает JSON `{"status": "ok"}` с кодом 200 (содержимое HTML заменяется; маршрут и путь не меняются). Проба health_check принимает только 200.

**Rationale**: FR-002 требует честной готовности; JSON — дефолт для API-платформы; изменение содержимого не ломает существующих потребителей (HTML-страница не была контрактом).

**Альтернативы**: оставить HTML и парсить статус-код — отклонено (FR-002: содержимое должно отражать статус).

**Остаток неопределённости**: во время пробы сервер может отвечать до полной инициализации ядра — приемлемо: контракт «принимает запросы» ≠ «все адаптеры подключены» (ядро поднимается до uvicorn в `run_platform`).

## R3. Точечная верификация Docker (остаток enhancement 20)

**Наблюдение** (сверено 2026-09-29):
- `Dockerfile` уже переписан: `COPY pyproject.toml` (не requirements.txt), слои кэширования, `CMD ["python", "-m", "src.main"]` ✓
- `src/main.py` существует: uvicorn, SIGTERM/SIGINT → graceful shutdown, loguru из `LOG_LEVEL`, `adapter.stop()`, `fsm.shutdown()` ✓
- `pyproject.toml` содержит uvicorn ✓; `/health` существует ✓
- **Не верифицировано**: фактические `docker build` и `docker compose up` никогда не прогонялись

**Decision**: верификация — обязательный шаг Phase 2 (запуск в quickstart): `docker build` → `compose up` → наблюдение статуса health → `docker stop` → просмотр логов на «Unclosed client session»/tracebacks. Фиксы Dockerfile — только по факту упавшей проверки.

**Rationale**: docker в рабочей среде доступен (`docker info` OK); гипотезы из enhancement уже частично опровергнуты — нельзя планировать правки, не увидев реальный результат сборки.

## R4. Реализация TTL интентов: место и форма

**Наблюдение**:
- `CommandIntent` определён в `src/core/commands/dispatcher.py:20` (Pydantic BaseModel): `device_id, domain, service, data, priority, source` — файл `models.py` из enhancement **не существует**
- `CommandDispatcher` создаётся в `src/core/container.py:164`; `bootstrap_platform` лишь собирает `Container`
- Методы называются `submit()`/`release()` (не `acquire()`)
- `asyncio.Lock` отсутствует; `container` не вызывает start/stop диспетчера; `src/main.py` не знает о диспетчере

**Decision**:
- Поля TTL — в `CommandIntent` (`last_updated`, `ttl_seconds=3600.0`, `refresh()`, `is_expired()`)
- Cleanup-loop + `asyncio.Lock` + `start()/stop()` — в `CommandDispatcher`
- Lifecycle: запуск в `Container.build()` (после создания диспетчера), останов в shutdown-пути `PlatformContext`/`src/main.py`
- `submit()` при успехе/повторном захвате вызывает `intent.refresh()`

**Rationale**: следует фактической кодовой базе вместо устаревших имён enhancement; lock охватывает и `_active_intents` в submit/release (FR-011).

**Альтернативы**: отдельный сервис-очиститель — отклонено (state живёт внутри диспетчера); per-intent `asyncio.TimerTask` — отклонено (N фоновых задач на N устройств, сложнее отлаживать).

## R5. Метрика обрывов WebSocket

**Наблюдение**: `src/services/metrics_server.py` использует `prometheus_client` (`generate_latest`); метрики проекта регистрируются при инициализации (сервер отдаёт `/metrics`).

**Decision**: добавить Counter `websocket_disconnects_total` и инкрементировать на каждой попытке reconnect в `ha_adapter._connect_websocket` (при ветке «WebSocket lost»/после ошибки соединения). Регистрация — при первом инкременте через ту же инфраструктуру метрик (без циклических импортов: ленивая регистрация, как принято в проекте).

**Rationale**: enhancement 21 прямо требует метрику «при наличии metrics» — подсистема есть.

**Альтернативы**: только логи — отклонено (FR-006 требует и лог, и счётчик); OpenTelemetry — не используется в проекте.

## R6. Тестирование реконнекта

**Decision**: `tests/test_ha_adapter_reconnect.py` на уровне `HAAdapter`:
1. mock-WS-клиент, чей `_listen_task` завершается после первого подключения → адаптер вызывает `connect()` повторно (2-я итерация while)
2. порядок backoff 1→2→4… (monkeypatch ожидания/времени)
3. shutdown во время ожидания задержки → мгновенный выход, нет висящих тасков (`asyncio.all_tasks()` — только текущий)
4. детект обрыва: `connected=False` + завершённый listen_task = новая попытка

**Rationale**: `ha_adapter` уже содержит цикл (`_connect_websocket`, FIRST_COMPLETED, heartbeat) — тесты фиксируют текущее поведение и защищают от регрессий; отдельный интеграционный тест с реальной HA — вне scope (нет HA в CI).

## R7. Lifecycle shutdown-цепочки

**Decision**: `PlatformContext` (см. `container.py`) получает асинхронный `shutdown()`, который останавливает диспетчер (и уже имеющиеся ресурсы); `src/main.py` в `finally` после `server.serve()` вызывает `ctx.shutdown()` вместо/вместо `adapter.stop()+fsm.shutdown()` (если они уже в shutdown — не дублировать, сделать идемпотентно).

**Rationale**: FR-013 — cleanup-таск не должен переживать останов; единая точка останова в контейнере соответствует DI-архитектуре (принцип IV).

**Альтернативы**: напрямую из main.py дёргать диспетчер — отклонено: main не должен знать о внутренних компонентах.

## R8. Пороговые значения

**Decision** (из enhancement + spec):
- TTL интента: 3600с (1 час); интервал cleanup-проверки: 300с (5 минут); SC-004 «≤65 минут» = 60+5 ✓
- Backoff reconnect: 1с → ×2 → максимум 60с, сброс до 1с после успеха (уже в коде — тестами фиксируется)
- Healthcheck: таймаут пробы 5с, compose start_period 40с (не меняем)
- Graceful shutdown: ≤30с (мгновенная отмена ожиданий через `shutdown_event`)

**Альтернативы**: делать TTL настраиваемым через ENV/манифест — отклонено до появления требования (константа модуля; конституция против hardcoded в business-логике — здесь дефолт в модели с явным полем, переопределяемым при создании intent).
