# B29/B30: Следующие шаги диагностики

**Дата создания:** 2026-10-08
**Статус:** ✅ завершено 2026-10-08 — обе половины проверены живьём, дефект B29 дофикшен (см. ниже «Итог»).

## Итог (2026-10-08, финал)

- **B30 подтверждён:** `подписка на события подтверждена HA (22 шт.)`, события доходят, автоматика пишет переходы в `history.db`.
- **B29 подтверждён и дофикшен:** обрыв сети контейнера на 45 с (дважды: до и после фикса), опрос `/ready` каждые 0.5 с изнутри контейнера.
  - До фикса: 20 сэмплов «нет соединения» подряд, **ни один** без причины — причина жила на `_ws_client`, который cleanup обнуляет, а ретраи заменяют новым клиентом.
  - После фикса (`_last_disconnect_reason` на адаптере, «первая причина», сброс при подключении): **9 из 9 сэмплов** с причиной `нет соединения с Home Assistant (ConnectionClosedError: sent 1011 ... keepalive ping timeout)`, восстановление через 4 с.
  - Журнал стал конкретнее: `WebSocket lost (ConnectionClosedError: ... keepalive ping timeout)` вместо `WebSocket lost (listen task ended)`.
  - Тесты: `tests/unit/test_ha_adapter_disconnect_reason_survives_reconnect.py` (6).
- Наблюдения ниже сохранены как история диагностики.

## Текущее состояние

### Что сделано
- ✅ Разрыв WebSocket (B29): флаг `connected` сбрасывается в `finally`, причина запоминается, доходит до `/ready`
- ✅ Подписка на события (B30): ответ HA читается синхронно, подтверждение сохраняется, отброшенные события считаются
- ✅ Коммиты: `9711afd` (разрыв), `7640f19` + `2deb565` (подписка), `bab5f92` (документация)
- ✅ Контейнер пересобран, 2610 passed, `run_checks.sh` exit 0

### Что проверено в живой HA
- PING/PONG видны в логах → heartbeat работает
- `/ready` говорит `home_assistant: ok` → соединение есть
- **ПРОБЛЕМА:** события не приходят (0 переходов после рестарта)
- **ИНФОРМАЦИИ НЕ ХВАТАЕТ:** в логах нет записей о подписке вообще

## Следующий шаг: диагностика подписки

### Проблема: LOG_LEVEL=DEBUG перегружает логи

Сейчас каждую минуту в лог идёт ~1000 строк PING/PONG от websockets-библиотеки:
```
DEBUG:    > PING xx xx xx xx [binary, 4 bytes]
DEBUG:    < PONG xx xx xx xx [binary, 4 bytes]
```

Это скрывает важные записи о подписке:
- `HAAdapter: subscribed to state_changed` (WARNING)
- `HAAdapter: listen loop finished` (WARNING)
- `HAAdapter: подписка на state_changed НЕ подтверждена` (WARNING если ошибка)

### Исправление: включить LOG_LEVEL=INFO

В `deploy/docker/.env`:
```bash
# Было:
LOG_LEVEL=DEBUG

# Стало:
LOG_LEVEL=INFO
```

### Шаги проверки

1. **Отредактировать `.env`:**
   ```bash
   cd deploy/docker
   sed -i '' 's/LOG_LEVEL=DEBUG/LOG_LEVEL=INFO/' .env
   ```

2. **Пересобрать и перезапустить:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   sleep 60
   ```

3. **Посмотреть подписку:**
   ```bash
   docker compose -f docker-compose.prod.yml logs --tail=100 behavioral-platform | grep -i "subscribed\|subscription\|listen loop"
   ```

4. **Проверить события:**
   ```bash
   sqlite3 deploy/docker/data/history.db "SELECT COUNT(*) FROM fsm_transitions WHERE timestamp > strftime('%s','now') - 300;"
   ```
   Должно быть > 0 за последние 5 минут.

5. **Проверить готовность:**
   ```bash
   curl -s http://localhost:8125/ready | python3 -m json.tool | grep -A 2 home_assistant
   ```
   Должно показать "соединение установлено" (без причины разрыва).

## Что может быть найдено

### Сценарий 1: Подписка не вызывается
**Лог не содержит "subscribed"**
- Проверить: вызывается ли `adapter.start()`?
- Проверить: доходит ли до `await self._ws_client.subscribe(...)`?
- Смотреть стек вызовов в `src/adapters/ha_adapter.py:754`

### Сценарий 2: Подписка отвергается HA
**Лог содержит "НЕ подтверждена"**
- Причина будет указана (код ошибки HA)
- Это не баг B30 — значит, код дошёл до `subscribe()`
- Либо отправляем неверный формат, либо HA закрыла API (маловероятно)

### Сценарий 3: Подписка потеряется где-то после
**Лог содержит "subscribed", но событий не приходит**
- События идут (они должны быть, HA их отправляет)
- Они теряются либо в `_listen_loop`, либо в пути обработчика
- Добавить обра в `_listen_loop`, прямо после `async for raw in self.ws:` → `logger.debug(f"got frame: {len(raw)} bytes")`

## Файлы, которые нужны для следующей итерации

- Логи контейнера с LOG_LEVEL=INFO (последние 50 строк после рестарта)
- Результат `curl /ready | python3 -m json.tool`
- Результат запроса к БД: количество переходов за последние 5 минут
- (если найден сценарий 3) результат добавления `logger.debug(f"got frame: {len(raw)} bytes")`

## Связанные файлы в проекте

- `src/adapters/ha_adapter.py` — адаптер, строки 754 (subscribe), 309 (подтверждение подписки), 150 (listen_loop)
- `deploy/docker/.env` — конфиг контейнера, переменная `LOG_LEVEL`
- `.ai/01_PROJECT_STATE.md` — документация найденного (раздел B29/B30)
- `.ai/BACKLOG.md` — задача Q8 в очереди §1

## Заметки для разработчика

- Heartbeat работает (PING видны) → переподключение срабатывает (коммит `13769da`)
- Если событий нет, это не потеря соединения, а потеря подписки либо её неэффективность
- После определения причины может потребоваться добавить более информативное логирование (WARNING вместо INFO)
