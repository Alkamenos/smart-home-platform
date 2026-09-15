# Room Aggregation & Policies

**Приоритет:** MEDIUM
**Оценка:** 2 дня
**Категория:** Core Features

## Цель

Сделать комнаты активными участниками системы с агрегацией состояний и зональными политиками.

## Проблема

Сейчас `room` — это просто метка. Комнаты не агрегируют состояния устройств и не имеют политик.

## Предлагаемое решение

```yaml
rooms:
  - id: bedroom
    name: "Bedroom"
    aggregation:
      occupancy: "any_motion"   # any_motion | all_motion | majority
      temperature: "average"    # average | min | max
    policies:
      - type: night_mode
        schedule: "23:00-07:00"
        applies_to: "all_lights"
        action:
          brightness: 10
```

## План реализации

1. Создать `core/room_manager.py`
2. Агрегация состояний устройств в комнате
3. Зональные политики (policies)
4. Интеграция с `EventRouter`
5. Тесты

## Файлы

- `core/room_manager.py`
- `core/models/room.py`
- `tests/test_room_aggregation.py`

## Критерии успеха

- [ ] Комнаты агрегируют состояния устройств
- [ ] Зональные политики применяются автоматически
- [ ] Интеграция с `EventRouter`
- [ ] Покрытие тестами >= 80%
