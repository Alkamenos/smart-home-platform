# HANDOFF: Smart Home Platform (Leonid's House) — 2026-08-16

## Окружение
HA на RPi4; ZigBee (Z2M) + Wi-Fi + Яндекс Станции; репо `/config/.platform`;
активный манифест `/config/manifests/active.yaml` (копия `manifests/leonid_house.yaml`).

## Состояние фич
- **Climate** (4 зоны), **Ventilation** (2× Vakio), **Sensor health** — работают (см. старый handoff в git history).
- **Lighting v2.6** — задеплоено 2026-08-16, не падает. Группы (14): yard_floodlights,
  street_night, office, bedroom, kitchen_work, table, container, bathroom,
  garland_terrace, garland_street, garland_windows, xmas_a2 (+ см. манифест).
  - Helpers созданы для большинства групп; provisioning JSON на kitchen_work/table/
    container/xmas_a2 выдан (id 49–60) — **проверить создание**.
  - В real live: `street_night` (override-manual сработал вживую 20:06).
  - **Смоук-тест garland_terrace (A/B/C) — запланирован, не выполнен.**
- **Schema**: патч `SensorHealth`/`Ventilation` для `shplatform/schema/features.py` выдан —
  **проверить, что применён, и `shplatform validate` зелёный**.

## Ключевые решения этого сеанса
- Vlight-контракт (docs/SPEC.md): guards (vlight 10 c, expected 30 c), override 60 мин, anti-cycle 2 мин.
- Безопасное чтение состояний `_lg_state()` (иначе NameError, см. PYSCRIPT_RULES).
- Усыновление легаси-boolean как `vlight_entity` группы (опциональное поле манифеста).
- Кнопки: ZG-101ZL в event-режиме; action-entity отключён; device trigger легаси работает
  без entity; миграция кнопок = перенаправить target легаси-автоматизации на `vlight_<id>`.

## Workflow
```bash
./tools/deploy.sh            # validate+склейка+sanity+sync+рестарт
./tools/deploy.sh --smoke    # после рестарта
```

## Диагностика
`pyscript.light_debug` / `light_override_clear` / `vlight_toggle`;
`pyscript.climate_debug`, `vent_debug`, `sensor_health_status`, `override_status`.

## Roadmap
1. Завершить lighting: смоук garland_terrace → пачка уличных групп → остальные.
2. **Полив**: не поливать в дождь (прогноз), влажность почвы, календарь/интервалы.
3. Реальные датчики дверей/окон (замена open-doors mock).
4. Ночное окно + override «вечеринка/спим».
5. Яндекс Диалоги; автогенерация дашборда из манифеста; торшер (гостевая); умные выключатели.
