# Command Intent TTL & Auto-Release

**Приоритет:** HIGH
**Оценка:** 1 день
**Категория:** Production Bugfixes
**Статус:** PLANNING

> Файл — ТЗ для ИИ-реализатора.

## Цель

Исключить вечные блокировки устройств в `CommandDispatcher`: "забытые" `CommandIntent` должны освобождаться автоматически.

## Проблема (подтверждено аудитом кода)

`CommandDispatcher._active_intents` хранит текущего владельца устройства. Если FSM перешла в `idle`, не вызвав `release()` (краш, пропущенная ветка, баг таймера), устройство блокируется навсегда: intent'ы с более низким приоритетом (сцены, AI) больше никогда не пройдут. Защиты от утечки нет.

## Инструкции для ИИ-реализатора

### 1. `src/core/commands/models.py` — расширить `CommandIntent`

- Добавить поля: `last_updated: float = field(default_factory=time.time)`, `ttl_seconds: float = 3600.0`.
- Добавить методы:
  - `refresh()` — обновляет `last_updated = time.time()`;
  - `is_expired() -> bool` — `time.time() - last_updated > ttl_seconds`.

### 2. `src/core/commands/dispatcher.py` — cleanup-loop

- Параметры конструктора: `cleanup_interval: float = 300.0` (проверка раз в 5 минут).
- `async start()` — запуск `self._cleanup_task = asyncio.create_task(self._cleanup_loop())`; идемпотентный (не создавать второй таск).
- `async stop()` — cancel таска, await с подавлением `CancelledError`.
- `_cleanup_expired()`: под `self._lock` найти все intent с `is_expired()`; удалить каждый и логировать WARNING вида:
  `TTL EXPIRED: force-releasing {device_id} (source={intent.source}, idle {N:.0f} min) — possible missing release() in FSM`.
- В `acquire()`: при успешном захвате и повторном захвате тем же intent вызывать `intent.refresh()`; при вытеснении по приоритету логировать preempt.

### 3. Lifecycle

- Вызвать `dispatcher.start()` в `bootstrap.py` после сборки контейнера и `dispatcher.stop()` при shutdown в `src/main.py`.

### 4. Тесты `tests/test_dispatcher_ttl.py`

- Intent с `ttl_seconds=0.05` удаляется после `_cleanup_expired()`, устройство свободно для нового intent.
- `refresh()` продлевает жизнь intent.
- Конкурентные `acquire()` из двух корутин не дают гонки (проверить работу под `asyncio.Lock`).
- Preempt по приоритету продолжает работать.

## Файлы

| Файл | Действие |
|---|---|
| `src/core/commands/models.py` | расширить `CommandIntent` |
| `src/core/commands/dispatcher.py` | добавить start/stop/_cleanup_loop/_cleanup_expired |
| `src/bootstrap.py`, `src/main.py` | подключить lifecycle |
| `tests/test_dispatcher_ttl.py` | создать |

## Критерии успеха

- [ ] Забытые intent автоматически освобождаются после TTL (default 1h)
- [ ] Каждое принудительное освобождение — WARNING в логе с source
- [ ] Cleanup-таск корректно останавливается при shutdown
- [ ] Тесты проходят
