# Контракты: Health Check дома

**Feature**: `019-house-health-check` | **Date**: 2026-11-09

## 1. `GET /api/v1/problems`

Единый снимок проблем: обход дома + сторож + неприменённые команды.

**Ответ 200:**

```json
{
  "generated_at": "2026-11-09T12:00:00+05:00",
  "count": 2,
  "levels": {"info": 0, "warning": 1, "critical": 1},
  "problems": [
    {
      "id": "a1b2c3",
      "kind": "stale",
      "subject": "sensor.datchik_temperatury_spalnia_temperature",
      "name": "Спальня температура",
      "area": "Спальня",
      "level": "warning",
      "detail": "молчит 2.4 ч при ожидании 30 мин",
      "source": "health",
      "value": "21.4",
      "first_seen": "2026-11-09T11:00:00+05:00",
      "last_seen": "2026-11-09T12:00:00+05:00",
      "reasons": []
    }
  ]
}
```

`reasons` заполняется, когда несколько причин сгруппированы по одной сущности:

```json
{
  "id": "…",
  "subject": "switch.maslianyi_radiator",
  "level": "warning",
  "first_seen": "…",
  "reasons": [
    {"kind": "device_mismatch", "detail": "…", "level": "warning", "first_seen": "…", "last_seen": "…"},
    {"kind": "command_not_applied", "detail": "…", "level": "warning", "first_seen": "…", "last_seen": "…"}
  ]
}
```

**Правила:**

- `count` — число активных проблем (по причинам, не по группам).
- `levels` всегда содержит три ключа.
- `problems` отсортирован: `critical`, затем `warning`, затем `info`; внутри —
  по времени `first_seen`.
- `first_seen`/`last_seen` — с часовым поясом дома.
- Если обход ещё не проходил: `count: 0`, `problems: []`, `generated_at: null`.
- Если Home Assistant недоступен: `count` сохраняет активные проблемы, в списке
  есть `ha_disconnected` уровня `critical`, а новые «молчит» не появляются.

**Ошибки:** 500 только при внутреннем сбое; недоступность дома — не 500, а
проблема в списке.

## 2. `GET /api/v1/health` (совместимое расширение)

Существующие поля сохраняются: `generated_at`, `sensor_count`, `problems`,
`areas` (в `/api/v1/observation`). Добавляются:

```json
{
  "count": 2,
  "levels": {"info": 0, "warning": 2, "critical": 0},
  "problems": [ … ]
}
```

`problems` здесь — только проблемы обхода датчиков; сторож и команды в
`/api/v1/problems`. Это позволяет старым клиентам не меняться.

## 3. `GET /api/v1/observation` (без изменений)

Реестр показаний по локациям и комнатам. Health check его не меняет.

## 4. Persistent-уведомление Home Assistant

**Создание/обновление** (`persistent_notification.create`):

```json
{
  "notification_id": "behavioral_platform_house_problems",
  "title": "Проблемы дома: 2",
  "message": "Спальня: Температура — молчит; Гостиная: Радиатор — расхождение с прибором"
}
```

**Снятие** (`persistent_notification.dismiss`):

```json
{"notification_id": "behavioral_platform_house_problems"}
```

**Правила:**

- Одно уведомление на дом, идентификатор фиксированный.
- `title` содержит число активных проблем; `message` — человеческая сводка
  (`summary_text`), без технических идентификаторов, если есть имя.
- Состав не изменился → уведомление не трогаем; максимум одно обновление в
  24 часа, если проблемы держатся.
- Состав изменился → обновляем сразу на ближайшем обходе.
- Проблем нет → `dismiss`.
- Home Assistant недоступен → состояние `dirty`, повтор на следующем обходе;
  в журнале — предупреждение, обход не падает.

## 5. События журнала

Каждый обход пишет:

- `Обход дома: датчиков N, проблем M` (INFO);
- открытие проблемы: `проблема открыта: <kind> <subject> — <detail>` (WARNING);
- закрытие: `проблема закрыта: <kind> <subject> — <close_reason>` (INFO);
- уведомление: `уведомление HA: создано/обновлено/снято, проблем N` (INFO);
- недоступность дома: `обход не состоялся: состояния не прочитаны` (WARNING).

## 6. Конфигурация в манифесте

`automation_rules.sensor_health` (существующий раздел):

```yaml
sensor_health:
  battery_watch_entities:
    - sensor.datchik_temperatury_spalnia_battery
  check_interval_minutes: 15
  stale_min_hours: 2
  battery_low_percent: 20
  battery_silent_hours: 48
  command_grace_minutes: 5
  notification_repeat_hours: 24
```

Все поля необязательны; при отсутствии действуют значения по умолчанию из
`research.md`. Явное значение в манифесте сильнее значения по умолчанию.
