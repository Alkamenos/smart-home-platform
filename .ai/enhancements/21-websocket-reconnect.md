# WebSocket Reconnection Reliability

**Приоритет:** CRITICAL
**Оценка:** 1 день
**Категория:** Production Bugfixes
**Статус:** PLANNING

> Файл — ТЗ для ИИ-реализатора.

## Цель

Платформа обязана автоматически восстанавливать WebSocket-соединение с Home Assistant после рестарта HA, обрыва сети и т.п. — без вмешательства человека и без "тихого ослепления".

## Проблема (подтверждено аудитом кода)

В `src/adapters/ha_adapter.py` метод `_connect_websocket` после успешного `subscribe()` выполняет `await self._shutdown_event.wait()` и блокируется навсегда. При обрыве соединения внутренний `_listen_loop` клиента умирает (исключения заглушаются `except Exception: pass`), но адаптер об этом не узнаёт: цикл reconnect не срабатывает. Платформа перестаёт получать события, оставаясь "живой" по всем признакам.

## Инструкции для ИИ-реализатора

### 1. `HAAdapter._connect_websocket` — переписать логику ожидания/реконнекта

- После `subscribe()` ожидать ОДНОВРЕМЕННО две задачи через `asyncio.wait(..., return_when=FIRST_COMPLETED)`:
  1. `self._shutdown_event.wait()`
  2. reader-таск websocket-клиента (атрибут `_listen_task`, выставляется в `subscribe()`)
- Ключевой паттерн:

```python
listen_task = getattr(self._ws_client, "_listen_task", None)
tasks = [asyncio.create_task(self._shutdown_event.wait())]
if listen_task and not listen_task.done():
    tasks.append(listen_task)
done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
for t in pending:
    t.cancel()
if self._shutdown_event.is_set():
    break  # штатное завершение
logger.warning("HAAdapter: WebSocket lost, reconnecting...")
# continue -> следующая итерация while = reconnect
```

- Экспоненциальный backoff: старт 1s, x2 после каждой неудачи, максимум 60s; сброс в 1s после успешных connect+subscribe.
- Сон между попытками: `await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)` в обёртке `try/except asyncio.TimeoutError` — чтобы shutdown не ждал окончания backoff.
- Ловить `ConnectionError/OSError/asyncio.TimeoutError` отдельно от прочих исключений (прочие — `logger.exception`).
- Считать и логировать номер попытки реконнекта; при наличии metrics — инкрементировать `websocket_disconnects_total`.

### 2. `SimpleHAWebSocketClient` — сделать обрыв детектируемым

- `subscribe()` обязан сохранять `self._listen_task = asyncio.create_task(self._listen_loop())`.
- `_listen_loop`: убрать `except Exception: pass`. При ошибке: `self.connected = False`, warning в лог, выход из цикла (завершение таска = сигнал для адаптера).
- При повторном `connect()`: закрыть старое соединение (если есть), сбросить счётчики id сообщений и pending-futures.

### 3. Тесты `tests/test_ha_adapter_reconnect.py`

- Mock-клиент, чей `_listen_task` завершается после первого подключения → проверить, что адаптер делает вторую попытку `connect()`.
- Проверить последовательность backoff (monkeypatch `asyncio.sleep`).
- Проверить, что после shutdown не остаётся висящих тасков.

## Файлы

| Файл | Действие |
|---|---|
| `src/adapters/ha_adapter.py` | переписать `_connect_websocket`, доработать `SimpleHAWebSocketClient` |
| `tests/test_ha_adapter_reconnect.py` | создать |

## Критерии успеха

- [ ] При симуляции рестарта HA адаптер сам восстанавливает связь, поток событий возобновляется
- [ ] Backoff 1→2→4→…→60s, сбрасывается после успеха
- [ ] Нет утечек asyncio-тасков при многократных реконнектах
- [ ] Graceful shutdown прерывает ожидание мгновенно
- [ ] Новые тесты проходят
