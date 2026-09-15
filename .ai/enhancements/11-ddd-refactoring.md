# Domain-Driven Design Refactoring

**Приоритет:** MEDIUM
**Оценка:** 1-2 дня
**Категория:** Architecture Improvements

## Цель

Улучшить структуру `core/`, разбив её на доменные подмодули.

## Проблема

Папка `core/` содержит слишком много разнородных сущностей (файлов верхнего уровня), что затрудняет навигацию.

## Текущая структура

```
core/
├── fsm.py
├── event_bus.py
├── event_router.py
├── scheduler.py
├── loader.py
├── state_persistence.py
├── command_dispatcher.py
├── middleware.py
└── ...
```

## Предлагаемая структура

```
core/
├── fsm/
│   ├── engine.py
│   ├── state.py
│   ├── transitions.py
│   └── guards/
├── events/
│   ├── event_bus.py
│   └── event_router.py
├── scheduling/
│   ├── scheduler.py
│   └── timers.py
├── commands/
│   ├── dispatcher.py
│   └── middleware.py
├── persistence/
│   ├── state_persistence.py
│   └── context_manager.py
└── models/
    ├── manifest.py
    └── scene.py
```

## План реализации

1. Создать новые директории
2. Переместить файлы с сохранением публичного API
3. Обновить импорты во всех модулях
4. **Обязательно:** сохранить реэкспорт в `core/__init__.py` для обратной совместимости
5. Прогнать все тесты

## Файлы

- Все файлы в `core/` и зависимых модулях

## Критерии успеха

- [ ] Структура реорганизована по доменам
- [ ] Все импорты обновлены
- [ ] Все существующие тесты проходят без изменений
- [ ] Обратная совместимость через реэкспорт в `core/__init__.py`
