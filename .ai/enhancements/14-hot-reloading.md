# Hot-Reloading для Guard/Action функций

**Приоритет:** LOW
**Оценка:** 1-2 дня
**Категория:** Developer Experience

## Цель

Горячая перезагрузка Python-кода (guards, actions) без остановки платформы.

## Проблема

`services/config_watcher.py` умеет перечитывать YAML, но не может перезагрузить изменённые Python функции.

## Предлагаемое решение

Использовать `importlib.reload()` для модулей с guards/actions при изменении файлов:

```python
def reload_module(module_path: str) -> None:
    spec = importlib.util.spec_from_file_location("dynamic", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Перерегистрировать функции в registry
    for name, func in inspect.getmembers(module, inspect.isfunction):
        if hasattr(func, "__action__"):
            registry.register_action(name, func)
```

## План реализации

1. Расширить `services/config_watcher.py` для отслеживания `.py` файлов
2. Перезагрузка модулей с сохранением активных таймеров и состояний
3. Обновление реестра (`registry`) после перезагрузки
4. Тесты на стабильность состояний при перезагрузке

## Файлы

- `services/config_watcher.py`
- `core/registry.py` (поддержка перезаписи)
- `tests/test_hot_reload.py`

## Критерии успеха

- [ ] Изменённые `.py` файлы перезагружаются автоматически
- [ ] Активные таймеры и состояния сохраняются
- [ ] Ошибки в новом коде не роняют платформу
- [ ] Покрытие тестами >= 80%

## Риски

1. **Состояние в модулях** — глобальные переменные могут быть потеряны. **Mitigation:** хранить состояние только в `StatePersistence`.
2. **Гонки при перезагрузке** — события могут прийти во время перезагрузки. **Mitigation:** блокировка на время перезагрузки.
