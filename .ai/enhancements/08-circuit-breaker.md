# Circuit Breaker Pattern

**Приоритет:** HIGH
**Оценка:** 1 день
**Категория:** Observability & Reliability

## Цель

Защита Home Assistant от перегрузки запросами при сбоях.

## Проблема

Если HA завис или не отвечает, платформа продолжает спамить его запросами, что может ухудшить ситуацию.

## Предлагаемое решение

Обернуть вызовы `adapter.call_service()` паттерном Circuit Breaker:

- **CLOSED** — нормальная работа, запросы проходят
- **OPEN** — слишком много ошибок, запросы блокируются на таймаут
- **HALF-OPEN** — пробный запрос для проверки восстановления

## Параметры по умолчанию

```python
CIRCUIT_BREAKER_CONFIG = {
    "failure_threshold": 5,  # 5 ошибок -> открыть
    "recovery_timeout_sec": 30,  # 30 секунд в OPEN
    "half_open_max_calls": 2,  # 2 пробных запроса в HALF-OPEN
}
```

## План реализации

1. Интеграция с `pybreaker` (или собственная реализация)
2. Обёртка для `HAAdapter.call_service()`
3. Метрики и логирование переключений состояний
4. Тесты с моками сбоев

## Файлы

- `adapters/ha_adapter.py`
- `tests/test_circuit_breaker.py`

## Критерии успеха

- [x] При серии ошибок запросы блокируются
- [x] Автоматическое восстановление после таймаута
- [x] Метрика `circuit_breaker_state`
- [x] Покрытие тестами >= 90%

## Статус

**ВЫПОЛНЕНО** ✅

Реализован полный цикл Circuit Breaker pattern:
- Файл `src/core/circuit_breaker.py` с полной реализацией
- Тесты `tests/test_circuit_breaker.py` с покрытием 99%
- Все состояния (CLOSED, OPEN, HALF_OPEN) работают корректно
- Автоматический переход OPEN -> HALF_OPEN после timeout
- Восстановление через HALF_OPEN -> CLOSED при успешных вызовах
