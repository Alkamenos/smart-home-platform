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

- `core/metrics.py`
- `services/metrics_server.py`
- `tests/test_metrics.py`

## Критерии успеха

- [ ] Все ключевые метрики экспортируются
- [ ] Метрики можно скрейпить через `/metrics`
- [ ] Есть пример `grafana-dashboard.json`
- [ ] Покрытие тестами >= 80%
