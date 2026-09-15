# Digital Twin / Simulator

**Приоритет:** MEDIUM
**Оценка:** 2-3 дня
**Категория:** Core Features

## Цель

Полноценная симуляция работы платформы без Home Assistant.

## Проблема

Для тестирования сложных сценариев нужен реальный или Docker HA. Симулятор позволит гонять сценарии локально и быстро.

## Предлагаемое решение

```bash
smart-home simulate instances/my_house/manifest.yaml \
    --scenario tests/scenarios/night_motion.yaml \
    --speedup 60
```

Сценарий задаёт последовательность событий:

```yaml
scenario:
  - at: "23:30"
    event:
      entity: binary_sensor.kitchen_motion
      state: "on"
  - at: "23:35"
    event:
      entity: binary_sensor.kitchen_motion
      state: "off"
assertions:
  - at: "23:30:05"
    expect:
      entity: light.kitchen
      state: "on"
      brightness: 15   # night_light сработал
```

## План реализации

1. Создать `core/simulator.py`
2. CLI команда `cli/commands/simulate.py`
3. Виртуальное время (`freezegun` или симуляция тиков)
4. Эмуляция событий от датчиков
5. Тесты-сценарии

## Файлы

- `core/simulator.py`
- `cli/commands/simulate.py`
- `tests/test_simulator.py`

## Критерии успеха

- [ ] Симуляция работает без Home Assistant
- [ ] Виртуальное время и ускорение
- [ ] Сценарии-файлы с ассертами
- [ ] Покрытие тестами >= 80%
