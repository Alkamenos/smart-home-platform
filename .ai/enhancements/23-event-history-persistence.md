# Event History Persistence (Data Lake)

**Приоритет:** HIGH
**Оценка:** 2 дня
**Категория:** AI & Analytics
**Статус:** PLANNING

> Файл — ТЗ для ИИ-реализатора. Это фундамент для всех AI-фич: без истории событий предсказание поведения невозможно.

## Цель

Писать полную историю событий (сенсоры, команды, ручные действия) в локальное Time-Series хранилище, чтобы AI мог искать паттерны поведения.

## Проблема

`StatePersistence` хранит только ТЕКУЩЕЕ состояние FSM. История событий нигде не накапливается — обучать/анализировать нечего.

## Инструкции для ИИ-реализатора

### 1. Новый пакет `src/analytics/`

**`src/analytics/db.py` — `HistoryDatabase` (aiosqlite):**

- Схема:

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    value TEXT,
    source TEXT,
    context_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_entity_ts ON events(entity_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type_ts  ON events(event_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_ts       ON events(timestamp DESC);
```

- PRAGMA: `journal_mode=WAL`, `synchronous=NORMAL`.
- Методы: `connect()`, `close()`, `insert_event(...)`, `commit()`, `get_patterns(entity_id, days=7, limit=1000) -> list[row]`, `cleanup_older_than(days=90) -> int`.
- Путь к БД: ENV `HISTORY_DB_PATH`, default `data/history.db`; директории создавать автоматически.

**`src/analytics/history_recorder.py` — `HistoryRecorder`:**

- `on_event(event)` — колбэк для EventBus: НЕблокирующий, только append словаря в in-memory буфер (timestamp, event_type, entity_id, value→str, source, context→json.dumps(default=str)).
- Пропускать шум: типы событий из `SKIP_EVENT_TYPES = {"heartbeat", "internal.tick", "metrics.update"}`.
- `_flush_loop` — раз в `flush_interval=10s`: под `asyncio.Lock` подменить буфер, батч-insert + один `commit()`. При ошибке БД — вернуть батч в буфер, логировать.
- `_cleanup_loop` — раз в 24h: `cleanup_older_than(90)`.
- `start()/stop()` — управление тасками; `stop()` делает финальный flush и закрывает БД.

### 2. Интеграция в `src/bootstrap.py`

- Создать `HistoryDatabase` + `HistoryRecorder`, `await recorder.start()`.
- Подписать на все события EventBus (wildcard `"*"` или `subscribe_all` — использовать механизм из `event_bus.py`).
- Зарегистрировать в DI-контейнере под ключом `history_recorder` (понадобится Predictive AI).
- При shutdown платформы: `await recorder.stop()`.

### 3. Инфраструктура

- Добавить `aiosqlite>=0.19` в `pyproject.toml`.
- Добавить `data/` в `.gitignore`.

### 4. Тесты `tests/test_history_recorder.py`

- Событие → после flush оказывается в БД.
- Шумовые события не пишутся.
- `stop()` полностью сбрасывает буфер.
- `cleanup_older_than` удаляет старые записи.
- `on_event` не выполняет блокирующих операций с БД (EventBus не тормозит).

## Файлы

| Файл | Действие |
|---|---|
| `src/analytics/__init__.py`, `db.py`, `history_recorder.py` | создать |
| `src/bootstrap.py` | подключить recorder |
| `pyproject.toml`, `.gitignore` | зависимость / ignore |
| `tests/test_history_recorder.py` | создать |

## Критерии успеха

- [ ] Все значимые события сохраняются в `data/history.db`
- [ ] Запись не тормозит EventBus (буфер + батч-flush)
- [ ] Retention: записи старше 90 дней удаляются автоматически
- [ ] Работает API `get_patterns(entity_id, days)` — основа для AI
- [ ] Тесты проходят
