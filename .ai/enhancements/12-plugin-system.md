# Plugin System

**Приоритет:** LOW (Future)
**Оценка:** 2-3 дня
**Категория:** Architecture Improvements

## Цель

Динамическое обнаружение и загрузка сторонних поведений (behaviors), адаптеров и middleware.

## Проблема

Добавление новых типов поведений сейчас требует форка ядра.

## Предлагаемое решение

Использовать `entry_points` в `pyproject.toml`:

```toml
[project.entry-points."smart_home.behaviors"]
party_mode = "my_party_plugin.behavior:PartyModeBehavior"

[project.entry-points."smart_home.middleware"]
geo_fence = "my_geo_plugin.middleware:GeoFenceMiddleware"
```

Загрузчик обнаруживает плагины автоматически при старте.

## План реализации

1. `core/plugin_loader.py` — обнаружение через `importlib.metadata`
2. Интерфейсы (протоколы) для типов плагинов:
   - `BehaviorPlugin`
   - `MiddlewarePlugin`
   - `AdapterPlugin`
3. Метаданные плагинов (версия, зависимости)
4. Документация и пример плагина в `examples/`
5. Тесты

## Файлы

- `core/plugin_loader.py`
- `core/plugin_interfaces.py`
- `docs/plugins.md`
- `examples/sample_plugin/`

## Критерии успеха

- [ ] Плагины обнаруживаются автоматически
- [ ] Можно добавлять поведение без изменения ядра
- [ ] Валидация версий и конфликтов плагинов
- [ ] Рабочий пример плагина
