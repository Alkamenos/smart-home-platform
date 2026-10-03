# Prometheus / OpenTelemetry Metrics

**Приоритет:** HIGH
**Оценка:** 1-2 дня
**Категория:** Observability & Reliability

## Цель

Production-ready мониторинг платформы через метрики.

## Проблема

Сейчас для отладки есть только логи с `trace_id`. Для production нужны метрики.

## Метрики для экспорта

| Метрика | Тип | Описание |
|---------|-----|----------|
| `fsm_transitions_total` | Counter | Переходы по состояниям и устройствам |
| `event_processing_latency_seconds` | Histogram | Задержка обработки событий |
| `ha_adapter_connection_errors_total` | Counter | Ошибки соединения с HA |
| `middleware_conflicts_total` | Counter | Срабатывания конфликтов |
| `command_dispatcher_rejections_total` | Counter | Отклонённые команды |
| `active_fsm_instances` | Gauge | Активные инстансы FSM |

## План реализации

1. Интеграция с `prometheus-client` (или `opentelemetry`)
2. Сервер метрик на порту (например, `9090`)
3. Инструментация `FSMEngine`, `CommandDispatcher`, `HAAdapter`
4. Документация по подключению к Prometheus/Grafana

## Файлы

**Актуально (specs/008-fsm-observability, 2026-10-02):**

- `src/core/metrics.py` — сборщик показателей
- `src/services/metrics_reporter.py` — учёт переходов, отказов и восстановлений
- `src/webui/routes/__init__.py` — маршрут `GET /metrics` на порту платформы
- `src/services/watchdog.py` — показатели сторожа
- `tests/test_metrics.py`, `tests/unit/services/test_metrics_reporter.py`,
  `tests/unit/services/test_watchdog.py`, `tests/contract/test_metrics_contract.py`

**Удалено 2026-10-02 как мёртвое:**

- `services/metrics_server.py` — неподнятый сервер на собственном порту; решение
  D-2: показатели отдаёт сервер платформы, отдельный порт не поднимается
- `src/smart_home/core/metrics.py`, `src/smart_home/services/metrics_server.py` —
  параллельное зеркало, недостижимое из production-кода

## Что изменилось при реализации

- Отдельный сервер метрик на порту 9090 **не поднимается**: наблюдаемость не
  должна быть второй точкой отказа. Метрики отдаёт `GET /metrics` на порту
  платформы рядом с `/health`.
- Метрики не оборачиваются в JSON: ответ — текстовый документ в стандартном
  формате сбора данных.
- Число различных наборов меток ограничено; переходы со сверхлимитными
  значениями агрегируются в серию `__other__`, сумма не теряется.
- Добавлены счётчики отказов (`fsm_rejections_total`), восстановлений состояний
  (`fsm_states_restored_total`) и показатели сторожа
  (`fsm_stuck_current`, `watchdog_checks_total`, `ha_connection_lost`).

## Критерии успеха

- [x] Все ключевые метрики экспортируются — семейства присутствуют в ответе
  с момента старта, до первого события (SC-004)
- [x] Метрики можно скрейпить через `/metrics` — проверено вживую на порту
  платформы; тип содержимого текстовый
- [ ] Есть пример `grafana-dashboard.json` — **не реализовано**, отдельная задача
- [x] Покрытие тестами >= 80% — тесты на настоящей библиотеке, без заглушек

**Статус:** реализовано в specs/008-fsm-observability (2026-10-02). До этого
расширение было помечено выполненным при полностью неработающем сборе
показателей: `initialize()` нигде не вызывался, `/metrics` не существовало.
