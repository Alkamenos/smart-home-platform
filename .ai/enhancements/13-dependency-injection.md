# Dependency Injection

**Приоритет:** LOW (Future)
**Оценка:** 2-3 дня
**Категория:** Architecture Improvements

## Цель

Улучшить модульность и тестируемость через явное внедрение зависимостей.

## Проблема

`bootstrap_platform()` создаёт много объектов с перекрёстными ссылками, что затрудняет тестирование отдельных компонентов.

## Предлагаемое решение

Лёгкий DI-контейнер (без тяжёлых фреймворков):

```python
class Container:
    def __init__(self, config: Manifest):
        self.config = config
        self._engine = None
        self._adapter = None

    @property
    def engine(self) -> FSMEngine:
        if self._engine is None:
            self._engine = FSMEngine(config=self.config)
        return self._engine

    @property
    def adapter(self) -> HAAdapter:
        if self._adapter is None:
            self._adapter = HAAdapter(engine=self.engine, config=self.config)
        return self._adapter
```

## План реализации

1. `core/container.py` — контейнер с ленивой инициализацией
2. Перенести логику из `bootstrap_platform()` в контейнер
3. Компоненты получают зависимости через параметры конструктора
4. Тесты с моками через контейнер

## Файлы

- `core/container.py`
- `bootstrap.py`
- `tests/test_container.py`

## Критерии успеха

- [ ] Все компоненты создаются через контейнер
- [ ] Компоненты не знают друг о друге напрямую
- [ ] Тесты используют моки через контейнер
- [ ] Покрытие тестами >= 85%
