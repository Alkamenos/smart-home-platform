# Operational Contracts: Критические продакшен-фиксы (Phase 9.8)

**Статус**: Phase 1 завершён | **Дата**: 2026-09-29
**Фича**: `specs/003-critical-production-fixes`

Внешние интерфейсы этой фичи — не пользовательские API, а эксплуатационные контракты: healthcheck, метрики, логи, сигналы остановки.

## 1. Healthcheck контейнера (FR-001, FR-002, SC-001)

**Потребитель**: `docker-compose.prod.yml` → `healthcheck.test: ["CMD", "python", "-m", "src.cli.health_check"]`

**Контракт модуля `src/cli/health_check.py`**:

| Условие | Exit code | stdout |
|---|---|---|
| HTTP-проба `GET /health` вернула 200 | `0` | краткое подтверждение (одна строка) |
| Соединение отклонено / таймаут / не-200 | `1` | диагностика причины |

- URL пробы: `http://127.0.0.1:{WEBUI_PORT}/health`, `WEBUI_PORT` по умолчанию **8125**
- Таймаут пробы: ≤5 секунд (общий budget контейнера: compose `timeout: 10s`)
- Поведение: одно выполнение и выход (никакого цикла — healthcheck запускает Docker)

**Контракт маршрута `/health`** (изменение содержимого):

```http
GET /health → 200
Content-Type: application/json

{"status": "ok"}
```

Не-200 не используется как «not ready»: до готовности сервер не отвечает вовсе (соединение отклонено → exit 1).

## 2. Жизненный цикл контейнера (FR-003, SC-006)

| Сигнал | Ожидаемое поведение |
|---|---|
| `docker stop` (SIGTERM) | graceful shutdown ≤30с: останов cleanup-таска диспетчера → останов адаптера → сохранение состояний FSM → завершение uvicorn; без traceback/«Unclosed client session» в логах |
| SIGINT (локальный запуск) | идентично SIGTERM |
| Ожидание reconnect/backoff во время остановки | отменяется мгновенно (`shutdown_event`), не блокирует выход |

## 3. Метрики (FR-006)

Инфраструктура: `prometheus_client` через `src/services/metrics_server.py` (`/metrics`).

| Метрика | Тип | Когда инкрементируется |
|---|---|---|
| `websocket_disconnects_total` | Counter | каждая зафиксированная потеря соединения/начало попытки восстановления в `ha_adapter._connect_websocket` |

Существующие метрики не переименовываются и не сбрасываются.

## 4. Логи (FR-006, FR-009)

Формат: loguru (существующая конфигурация `src/main.py`, уровень из `LOG_LEVEL`).

| Событие | Уровень | Обязательные поля в сообщении |
|---|---|---|
| Обрыв WebSocket и начало восстановления | WARNING | факт обрыва, номер попытки, задержка |
| Успешное переподключение | INFO | факт успеха, сброс backoff |
| Force-release интента по TTL | WARNING | `device_id`, `source`, длительность удержания в минутах, подсказка про возможный пропущенный `release()` в FSM |
| Ошибка подключения (кроме ConnectionError/OSError/Timeout) | ERROR (+`logger.exception`) | тип и текст исключения |

Трассировка: существующий `trace_id`-паттерн сохраняется там, где он уже применяется; новые сообщения не создают собственных систем логирования.

## 5. Lifecycle диспетчера (FR-013)

```text
Container.build()          → dispatcher.start()   # запуск cleanup-loop (идемпотентно)
PlatformContext.shutdown() → dispatcher.stop()    # cancel cleanup_task, подавление CancelledError
src/main.py finally        → ctx.shutdown()       # единая остановка ресурсов
```

- Повторный `start()` не создаёт второй cleanup-таск
- `stop()` без предварительного `start()` — no-op (безопасно)
- Cleanup-интервал: `cleanup_interval=300.0`с (параметр конструктора, дефолт)

## 6. Верификация Docker (SC-001, SC-006)

Не контракт кода, а обязательная процедура валидации (см. quickstart.md):

```bash
docker build -f deploy/docker/Dockerfile -t smart-home-platform:003 .
docker compose -f deploy/docker/docker-compose.prod.yml up -d
docker compose ps   # ожидаем: healthy
docker stop <id>    # ожидаем: graceful shutdown без ошибок
```

Фактические отклонения от этого контракта фиксируются в tasks.md как задачи-фиксы (Dockerfile/сборка изменяются только по результату).
