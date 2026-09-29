# Data Model: Критические продакшен-фиксы (Phase 9.8)

**Статус**: Phase 1 завершён | **Дата**: 2026-09-29
**Фича**: `specs/003-critical-production-fixes`

## Сущности

### CommandIntent (расширение, `src/core/commands/dispatcher.py`)

Право источника управлять устройством. Существующие поля сохраняются.

```
CommandIntent (Pydantic BaseModel)
├── device_id: str              # (есть) целевое устройство, напр. "light.kitchen"
├── domain: str                 # (есть) домен сервиса HA
├── service: str                # (есть) имя сервиса
├── data: Dict[str, Any]        # (есть) данные вызова
├── priority: int               # (есть) приоритет (выше = сильнее)
├── source: str                 # (есть) источник (сцена, AI, пользователь)
├── last_updated: float         # НОВОЕ: time.time() последнего обновления/захвата
└── ttl_seconds: float = 3600.0 # НОВОЕ: время жизни; дефолт 1 час
```

**Новые методы**:
- `refresh() -> None` — `last_updated = time.time()`
- `is_expired() -> bool` — `time.time() - last_updated > ttl_seconds`

**Правила валидации**:
- `ttl_seconds >= 0` (значение 0 допустимо — немедленное истечение, SC/edge case)
- Поля-дефолты не ломают существующих пользователей модели (обратная совместимость)

**Правила жизни (состояния)**:

```
(нет интента) --submit() успех--> [ACTIVE] --release(source)--> (свободно)
                                  [ACTIVE] --submit() того же source--> [ACTIVE] + refresh()
                                  [ACTIVE] --submit() приоритетнее--> [ACTIVE] (вытеснение, preempt-лог)
                                  [ACTIVE] --is_expired() при cleanup--> (свободно) + WARNING-лог
```

- Гонки исключаются: все мутации `_active_intents` — под `asyncio.Lock` диспетчера (FR-011)
- Семантика вытеснения по приоритету не меняется (FR-012)

### CommandDispatcher (расширение жизненного цикла)

```
CommandDispatcher
├── _active_intents: dict[str, CommandIntent]   # (есть)
├── _ha_adapter: HAAdapterProtocol              # (есть)
├── _middlewares: list[MiddlewareProtocol]      # (есть)
├── _lock: asyncio.Lock                         # НОВОЕ: защита _active_intents
├── _cleanup_task: asyncio.Task | None          # НОВОЕ: фоновая проверка TTL
├── cleanup_interval: float = 300.0             # НОВОЕ: параметр конструктора, сек
├── start() -> None                             # НОВОЕ: идемпотентный запуск cleanup-loop
├── stop() -> None                              # НОВОЕ: cancel + await, подавление CancelledError
├── _cleanup_loop()                             # НОВОЕ: sleep(cleanup_interval) → _cleanup_expired()
├── _cleanup_expired() -> int                   # НОВОЕ: удаление истёкших, возврат количества
├── submit(intent) -> bool                      # (есть) + intent.refresh() при успехе
└── release(device_id, source) -> bool          # (есть)
```

**WARNING при force-release** (FR-009):
`TTL EXPIRED: force-releasing {device_id} (source={intent.source}, idle {N:.0f} min) — possible missing release() in FSM`

### Состояние соединения с HA (существующая логика, фиксируется тестами и метрикой)

```
ConnectionState (наблюдаемое, не отдельный класс)
├── phase: "connecting" | "connected" | "reconnecting" | "stopped"
├── attempt: int                    # номер текущей попытки (логируется)
├── delay: float                    # текущая задержка backoff: 1 → ×2 → max 60, сброс после успеха
└── disconnects_total: Counter      # НОВОЕ метрика: websocket_disconnects_total
```

- Детект обрыва: завершение `_listen_task` клиента или `connected=False` → новая итерация цикла (уже в коде)
- Останов: `shutdown_event` отменяет ожидание задержки мгновенно (`wait_for(shutdown_event.wait(), timeout=delay)`)

### Статус готовности платформы (healthcheck)

```
HealthStatus (JSON-контракт /health)
├── status: "ok" | "error"        # 200 только при "ok"
└── (дополнительные поля не требуются для FR-002)
```

- Определение: маршрутизатор отвечает ⇒ ready (ядро инициализировано до старта uvicorn)
- `src/cli/health_check.py`: HTTP-проба → exit 0 (200) / exit 1 (иначе); таймаут 5с; порт `WEBUI_PORT` (дефолт 8125)

## Отношения

- CommandDispatcher → CommandIntent: 1:N (`_active_intents` по device_id, максимум 1 активный на устройство)
- HAAdapter → ConnectionState: 1:1 на процесс
- Платформа → HealthStatus: 1 на процесс

## Аутентификация/безопасность

- Не применимо: сущности оперативные, данные не персистируются, новые сетевые контракты — только localhost-проба healthcheck (внутри контейнера)
