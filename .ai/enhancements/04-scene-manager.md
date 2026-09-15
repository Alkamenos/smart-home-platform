# Scene Manager / Flow Engine

**Приоритет:** HIGH
**Оценка:** 2-3 дня
**Категория:** Core Features

## Цель

Управление сложными сценариями, затрагивающими несколько устройств одновременно или последовательно.

## Проблема

FSM отлично работает для одного устройства, но для сцен вроде "Кинотеатр" (свет гаснет, шторы закрываются, ТВ включается) нужна надстройка.

## Предлагаемое решение

```yaml
scenes:
  - id: cinema_mode
    name: "Cinema Mode"
    actions:
      - device: light.living_room
        service: turn_off
      - device: cover.blinds
        service: close_cover
      - device: media_player.tv
        service: turn_on
        data:
          source: "Netflix"
    triggers:
      - type: time
        at: "19:00"
      - type: button
        entity: input_button.cinema
```

## План реализации

1. Создать `core/scene_manager.py`
2. Pydantic модель для сцен (`core/models/scene.py`)
3. Интеграция с `EventBus` для триггеров
4. Поддержка последовательных и параллельных действий
5. Тесты

## Файлы

- `core/scene_manager.py`
- `core/models/scene.py`
- `tests/test_scene_manager.py`

## Критерии успеха

- [ ] Сцены загружаются из манифеста
- [ ] Триггеры работают (time, button, state)
- [ ] Параллельные и последовательные действия
- [ ] Покрытие тестами >= 80%
