# Quickstart: валидация Phase 9.8 (Docker / WS-Reconnect / Intent TTL)

**Статус**: Phase 1 завершён | **Дата**: 2026-09-29
**Фича**: `specs/003-critical-production-fixes`
**Контракты**: [contracts/operational-contracts.md](contracts/operational-contracts.md) · **Модель**: [data-model.md](data-model.md)

Все сценарии выполняются из корня репозитория. Предусловие: установлены Python-зависимости проекта и Docker (`docker info` без ошибок).

---

## Сценарий 1 — Unit: healthcheck-модуль (FR-001, FR-002)

```bash
pytest tests/cli/test_health_check.py -v
```

**Ожидаемый результат**:
- проба к живому серверу с `/health` → exit 0
- недоступный порт / таймаут / не-200 → exit 1
- порт читается из `WEBUI_PORT`, дефолт 8125

Дополнительно (маршрут):

```bash
pytest tests/test_webui.py -k health -v
```

**Ожидаемый результат**: `GET /health` → 200, JSON `{"status": "ok"}`

## Сценарий 2 — Unit: восстановление WebSocket (FR-004…FR-007, SC-002, SC-003)

```bash
pytest tests/test_ha_adapter_reconnect.py -v
```

**Ожидаемый результат**:
1. mock-клиент с завершающимся `_listen_task` → адаптер делает повторную попытку `connect()`
2. backoff идёт 1 → 2 → 4 → … ≤60с, после успеха сбрасывается в 1с
3. shutdown во время задержки выходит мгновенно; после прогона нет «висящих» asyncio-задач
4. каждая потеря фиксируется в логе (WARNING + номер попытки) и метрикой `websocket_disconnects_total`

## Сценарий 3 — Unit: TTL командных интентов (FR-008…FR-013, SC-004, SC-005)

```bash
pytest tests/test_dispatcher_ttl.py -v
```

**Ожидаемый результат**:
1. интент с `ttl_seconds=0.05` после `_cleanup_expired()` освобождает устройство; новый intent проходит
2. `refresh()` продлевает жизнь — ложного срабатывания нет
3. конкурентные `submit()` из двух корутин не дают гонки (проверка под `asyncio.Lock`)
4. preempt по приоритету работает как раньше
5. force-release пишет WARNING с `device_id`, `source`, минутами удержания
6. `start()` идемпотентен; `stop()` не оставляет задач

```bash
pytest tests/test_dispatcher.py -v   # регресс: существующее поведение диспетчера не сломано
```

## Сценарий 4 — E2E: сборка и запуск контейнера (SC-001, SC-006)

```bash
# 1. Сборка на чистом хосте
docker build -f deploy/docker/Dockerfile -t smart-home-platform:003 .

# 2. Запуск
docker compose -f deploy/docker/docker-compose.prod.yml up -d

# 3. Статус контейнера
docker compose -f deploy/docker/docker-compose.prod.yml ps
# ожидаем: State "healthy" в пределах start_period (40с) + интервала (30с)

# 4. Проба health напрямую
curl -fsS http://localhost:8125/health
# ожидаем: {"status":"ok"} и HTTP 200

# 5. Наблюдение за стабильностью (10 минут, 0 перезапусков)
docker compose -f deploy/docker/docker-compose.prod.yml ps --format json | grep -o '"Restarting"' | wc -l
# ожидаем: 0
```

**Если шаг 1 упал** — зафиксировать ошибку сборки в tasks.md (фиксы Dockerfile только по факту; гипотезы enhancement 20 частично опровергнуты).

## Сценарий 5 — E2E: graceful shutdown (SC-006)

```bash
docker compose -f deploy/docker/docker-compose.prod.yml logs --tail 50
docker compose -f deploy/docker/docker-compose.prod.yml stop
docker compose -f deploy/docker/docker-compose.prod.yml logs --tail 100
```

**Ожидаемый результат**: останов ≤30 секунд; в логах нет `Traceback`, `Unclosed client session`, повторных ошибок healthcheck после остановки.

## Сценарий 6 — Регресс всего проекта (SC-007)

```bash
.ai/scripts/run_checks.sh
pytest tests/ --ignore=tests/contract --ignore=tests/integration -q
pytest tests/contract -q
pytest tests/integration -q
```

**Ожидаемый результат**: `run_checks.sh` exit 0; покрытие ≥80%; тесты контрактов/интеграций — 0 падений относительно baseline.

---

## Карта сценариев → критерии

| Сценарий | SC |
|---|---|
| 1. Healthcheck unit | SC-001 (компонент), SC-007 |
| 2. WS-Reconnect unit | SC-002, SC-003, SC-007 |
| 3. TTL unit | SC-004, SC-005, SC-007 |
| 4. Docker E2E | SC-001 |
| 5. Shutdown E2E | SC-006 |
| 6. Регресс | SC-007 |
