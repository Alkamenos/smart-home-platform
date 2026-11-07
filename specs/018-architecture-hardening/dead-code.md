# Инвентаризация мёртвого кода (T074)

**Дата:** 2026-11-07 | **Спека:** `018-architecture-hardening`, US6

## Инструмент

```bash
python tools/dead_code_inventory.py
```

Сканирует `src/` и `tests/`, ищет импорты по имени модуля и печатает модули,
на которые нет ни одной ссылки. Динамические импорты и точки входа исключены
вручную.

## Результат

На момент проверки кандидатов не осталось: таблица пуста.

Удалено в этой волне:

- `src/bootstrap.py` — заменён на `Container(...).build()` в CLI;
- `src/services/backup_service.py` и `tests/test_backup_service.py` — сервис не
  вызывался в production; резервное копирование остаётся в
  `deploy/scripts/deploy.sh backup`;
- `src/core/models/room.py` — параллельная модель комнаты, не использовалась;
- `src/core/services/state_snapshot.py` — не использовался.

## Guard'ы

Сверка `build_guards()` с `src/features/CONTRACT.yaml` показала 40
зарегистрированных имён и 32 используемых в шаблонах. Оставшиеся имена
(`is_day_time`, `below_setpoint`, `at_or_above_setpoint`, `climate_is_enabled`,
`managed_by_hardware_ok`, `stops_on_sunrise`, `sensor_is_alive`,
`has_usable_reading`) сохранены осознанно: они покрыты отдельными тестами и
используются как строительные блоки шаблонов; удаление сломало бы публичный
реестр guard'ов.
