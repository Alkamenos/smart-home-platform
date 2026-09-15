# Interactive REPL

**Приоритет:** LOW
**Оценка:** 0.5 дня
**Категория:** Quick Wins

## Цель

Интерактивная среда для разработки и отладки с доступом к `engine`, `adapter`, `registry`.

## Проблема

Для проверки изменений нужно постоянно писать тесты или демо-скрипты.

## Предлагаемое решение

```bash
smart-home shell

>>> await engine.trigger("binary_sensor.kitchen_motion", "motion_detected")
>>> engine.get_state("light.kitchen_lighting_10")
>>> await adapter.call_service("light", "turn_on", "light.kitchen")
```

## План реализации

1. CLI команда `cli/commands/shell.py`
2. Инициализация всех компонентов через `bootstrap_platform()`
3. Использование встроенного Python REPL или IPython (опционально)
4. Автодополнение (опционально)

## Файлы

- `cli/commands/shell.py`

## Критерии успеха

- [ ] REPL запускается без ошибок
- [ ] Доступ к `engine`, `adapter`, `registry`
- [ ] Поддержка вызова `async` функций
