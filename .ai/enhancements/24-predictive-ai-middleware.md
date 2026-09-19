# Predictive AI Middleware

**Приоритет:** MEDIUM
**Оценка:** 3–5 дней
**Категория:** AI & Advanced Features
**Статус:** PLANNING
**Зависимости:** требует выполненной `23-event-history-persistence`

> Файл — ТЗ для ИИ-реализатора. Главный принцип: AI НЕ ломает основную цепочку команд и НЕ перебивает пользователя/автоматизации.

## Цель

Научить дом предугадывать действия: на основе накопленной истории предлагать и (при разрешении) выполнять отложенные команды — например, приглушать свет перед сном.

## Проблема

Система чисто реактивная (FSM+Guards: "движение И темно → свет"). Обучения привычкам нет: паттерны ручных действий не анализируются, упреждающие сценарии отсутствуют.

## Инструкции для ИИ-реализатора

### 1. `src/core/middleware/predictive_ai.py` — `PredictiveAIMiddleware`

- Конструктор: `(history_recorder, dispatcher, scheduler, shadow_mode: bool)`.
- `async process(intent) -> intent` — контракт middleware диспетчера:
  - Всё тело в try/except: ЛЮБАЯ ошибка AI логируется и возвращает исходный intent (цепочка не должна рваться).
  - Вызвать `_analyze_and_predict(intent)`; есть предсказание → `_handle_prediction(pred)`.
- `_analyze_and_predict(intent)` — эвристики v1 БЕЗ ML:
  - Анализировать только ручные действия: `intent.source == "user_manual"`.
  - Окно "поздний вечер": 22:00–02:00 локального времени.
  - Через `history_recorder` получить паттерны по устройству за 14 дней; посчитать число аналогичных действий в вечернем окне; если >= 3 — вернуть dict `{action, target_device, delay_sec, params, confidence, reason}`, где `confidence = min(0.95, count/10)`.
  - Первый сценарий: `dim_late_night` — через 600s установить brightness 20 для света, который пользователь только что включил вручную.
- `_handle_prediction(pred)`:
  - Shadow mode (default ON, ENV `AI_SHADOW_MODE=true`): только лог
    `[AI PREDICTION] Would {action} on {device} in {delay}s (confidence {X}%): {reason}`.
  - Live mode: создать `CommandIntent(priority=IntentPriority.AI_PREDICTION, source="ai_prediction", ttl_seconds=delay+300)` и запланировать отложенно через scheduler; перед фактическим выполнением перепроверить, что пользователь не вмешался вручную (свежие manual-события в истории).

### 2. `IntentPriority`

- Добавить `AI_PREDICTION = 30` — НИЖЕ FSM_AUTO(50) и USER_MANUAL(100): AI никогда не перебивает автоматизации и пользователя.

### 3. `src/analytics/routine_analyzer.py` — `NightlyRoutineAnalyzer`

- Ночная задача через scheduler (03:00):
  1. Собрать выжимку событий за 24h из HistoryDatabase (топ событий, manual overrides, срабатывания FSM).
  2. Отправить LLM через `LLMAdapter` (см. `.ai/enhancements/10-llm-nlp-adapter.md`) с промптом: "предложи 1–5 улучшений правил, ответ строго JSON-массив `[{rule_name, suggestion, reason, priority}]`".
  3. Парсить ответ устойчиво: обрезать markdown-обёртки, искать от первой `[` до последней `]`.
  4. Сохранять в `data/ai_suggestions/YYYY-MM-DD.json` + логировать. АВТОМАТИЧЕСКИ НЕ ПРИМЕНЯТЬ — только human-in-the-loop.
- Если `LLMAdapter` ещё не реализован: analyzer обязан деградировать без падения (лог "LLM unavailable, skipping").

### 4. Интеграция в `src/bootstrap.py`

- Создавать middleware и добавлять в цепочку dispatcher ПОСЛЕ `ManualLockoutMiddleware`.
- ENV-флаги: `AI_ENABLED` (default `false`), `AI_SHADOW_MODE` (default `true`).

### 5. Тесты `tests/test_predictive_middleware.py`

- Shadow mode: предсказание залогируется, команды не создаются.
- Live mode: создаётся отложенный intent с приоритетом AI_PREDICTION.
- Исключение внутри `_analyze_and_predict` → исходный intent возвращается, цепочка жива.
- Парсер ответа парсит JSON с markdown-обёрткой и без.

## Файлы

| Файл | Действие |
|---|---|
| `src/core/middleware/predictive_ai.py` | создать |
| `src/core/commands/models.py` | добавить IntentPriority.AI_PREDICTION |
| `src/analytics/routine_analyzer.py` | создать |
| `src/bootstrap.py` | подключить middleware + ENV-флаги |
| `tests/test_predictive_middleware.py` | создать |

## Критерии успеха

- [ ] Ошибки AI никогда не ломают выполнение команд
- [ ] Shadow Mode логирует предсказания, не выполняя их (первые 1–2 недели production)
- [ ] AI_PREDICTION приоритет ниже FSM и USER
- [ ] Nightly analyzer сохраняет предложения в `data/ai_suggestions/`, сам их не применяет
- [ ] Тесты проходят
