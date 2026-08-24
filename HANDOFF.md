Вот сжатый handoff-промт. Вставьте его в новый диалог — он содержит цель, архитектуру, текущее состояние, технические ограничения и следующие шаги.

---

# HANDOFF: Smart Home Platform (Leonid's House)

## Цель
Строим **data-driven платформу умного дома** поверх Home Assistant как продукт для тиражирования. Ключевые требования: лёгкая модификация; миграция с легаси без поломок; настройка через UI (без YAML); учёт внешних условий; распознавание источника команды (физический выключатель/Алиса/автоматика) для отсутствия конфликтов.

## Окружение
- HA на Raspberry Pi 4, аддон VS Code (git), репо `/config/.platform`
- ZigBee (Zigbee2MQTT) + Wi-Fi + Яндекс Станции
- Репозиторий уже содержит рабочие модули: climate, ventilation, sensor_health, lighting v2

## Архитектура (принятые решения)
- **Манифест (YAML)** = единый источник правды инстанса. Pydantic-схема + валидатор CLI, runtime-лоадер НЕ использует Pydantic.
- **Разделение**: HA-native (helpers, Lovelace) для UI; **pyscript** для логики.
- **Конкатенация** 7 файлов в один `/config/pyscript/manifest_loader.py`:
  `registry.py` → `manifest_loader.py` → `climate_orchestrator.py` → `ventilation_controller.py` → `sensor_health.py` → `lighting_controller.py`
- **Shadow/real** у каждой фичи через master-выключатель и shadow-тумблер.
- **Override Manager**: слушает `state_changed` управляемых устройств, отличает «команда платформы» от внешнего и ставит временный блок. Реализован опросно (не глобальным event_trigger) из-за нагрузки на RPi4.
- **Команды только при переходе** + уважение ручных правок + анти-цикл (мин. 2 мин между командами).

## Критичные ограничения pyscript (важно!)
- Нет общего namespace между файлами → **обязательна склейка**.
- `@time_trigger("period=30")` не парсится → `@time_trigger("startup")` + бесконечный цикл `task.sleep(30)`.
- После `pyscript.reload` дубли фоновых циклов → **всегда полный перезапуск HA**.
- `climate` state = hvac_mode (cool/off/…), НЕ on/off → `_clim_is_on` отдельно.
- `@event_trigger("state_changed")` глобально = спам/перегрев event loop → только целевые подписки (`@state_trigger` по списку entity).

## Что ГОТОВО (работает в real)

### Climate (4 зоны: гостиная/санузел/спальня/кабинет)
- Heat/Cool оцениваются ВСЕГДА (не привязаны к сезону) — двунаправленно.
- Конкретные hvac-режимы (`cool`/`heat`/`off`), никогда `auto`.
- Safety: AC winter lockout + голосовое предупреждение через Яндекс; AC dry летом при влажности; вентилятор санузла.
- Free-heat координация: когда рекуператоры греют уличным воздухом — климат не включает электрообогрев.

### Ventilation (Vakio Base Smart × 2: спальня, кабинет)
- Пресеты: `Приток / Приток MAX / Рекуперация (лето) / Рекуперация (зима) / Вытяжка / Вытяжка MAX / Ночной`. Скорость через `percentage` 0–100.
- Профили: boost (приток/вытяжка) с авто-выклом, зимняя пауза (если конвекторы греют), free cooling/heating, ночной режим, away-режим.
- Open-doors: сейчас mock через `input_boolean.open_doors_mock_state` + `feature_open_doors` флаг; реальные датчики — future.

### Sensor health
- Детект `unavailable` + низкая батарея; одно обновляемое persistent-уведомление; **агрегированный список покупок** вида «Батарейка CR2450 - 2 шт».
- Тип и количество батарейки в манифесте для каждого датчика.
- Контроллеры безопасно пропускают мёртвые датчики (зона на паузе).

### Lighting v2 (12 групп + vlight-слой + select+time UI)
- **vlight-слой**: Виртуальные `input_boolean.vlight_<group_id>` для управления кнопками/дашбордом/Алисой
  - Синхронизация с реальными лампами
  - Учет ручных изменений vlight как override
  - Сервис `pyscript.vlight_toggle(group_id)` для кнопок
- **Select+Time UI**: `input_select.light_<id>_on` (Не включать/Закат/Время) + `input_datetime.light_<id>_on_time`
- **Профили**: `dusk_till_time`, `dusk_till_dawn`, `motion`, `manual_auto` (+ future `nightlight`, `backlight`)
- **Цветовая температура**: кривая 2000–6000K (day_kelvin → night_kelvin с warm_from/night_from)
- **Backlight выключателей**: schedule/always/off, в спальне — inverse/motion
- **Имитация присутствия**: случайно вкл 1–2 manual-группы на 10–30 мин (окно input_datetime, при my_doma=off)
- **Сезонные варианты**: напр. `garland_windows`: лето = dusk_till_dawn антимоскитная, зима = dusk_till_time гирлянда
- **Free-heat координация** с климатом
- **Дашборд**: полный UI для управления освещением (12 групп с toggle/select/time)

### Дашборд Smart Home
- Статус платформы (сезон, дома/нет, вечер)
- Климат (4 зоны + уставки)
- Вентиляция (2 рекуператора + boost режимы)
- Освещение (12 групп с vlight toggle + select + time UI)
- Sensor health (статус + список покупок батареек)
- Debug сенсоры

## Следующие шаги (roadmap)
- **Кнопки управления освещением**: маппинг «кнопка → toggle vlight» (ждём entity_id кнопок)
- **Полив**: не поливать в дождь, влажность почвы, календарь
- **Реальные датчики дверей/окон**: замена open-doors mock
- **Ночное окно**: `input_datetime` + override «вечеринка»/«спим сейчас»
- **Яндекс Диалоги**: голосовой интерфейс
- **Автогенерация дашборда** из манифеста (для тиражирования)
- **Сенсор `torsher`**: починить ссылку во внешней автоматизации (гостевая, сейчас unavailable)
- **Замена обычных выключателей на умные**: future-группы в манифесте уже объявлены с `entity: null`

---


## 2. HANDOFF.md — инструкции для нового чата

```markdown
# Передача контекста в новый чат

## Что работает

### Освещение
- ✅ 14 групп света с vlight + auto/manual
- ✅ Мгновенная реакция на датчики движения через `@state_trigger`
- ✅ Ночник (table) с RGB и отдельным таймаутом
- ✅ Dropdown выбор датчика движения per group
- ✅ Режим "Датчик движения" в `input_select.light_*_on`
- ✅ Feature/shadow семантика: ручное всегда работает в real
- ✅ Имитация присутствия, RGB сцены, color temp

### Климат
- ✅ 4 зоны (гостиная, санузел, спальня, кабинет)
- ✅ Конвекторы + AC с deadband
- ✅ Season (зима/лето) через `input_boolean.zima`
- ✅ Safety: lockout AC зимой, осушение летом
- ✅ Override 120 мин после ручного управления

### Вентиляция
- ✅ 2× Vakio рекуператора
- ✅ Режимы: base, night, boost (intake/exhaust)
- ✅ Free heating/cooling (уличным воздухом)
- ✅ Вентилятор санузла (temp + humidity)
- ✅ Open doors lockout

### Дашборды
- ✅ 3 дашборда (home, settings, admin) через генераторы
- ✅ Mushroom cards
- ✅ Conditional карточки (показывать по условию)

## В процессе

### Освещение
- ⏳ Режим "Party" — должен держать включённое до рассвета, не включать выключенное
- ⏳ Keepalive для table — держать включённый при движении N мин, не включать выключенный днём
- ⏳ Глобальные таймауты движения (день/ночь) для всех групп кроме санузла
- ⏳ Санузел: запрет авто-включения ночью, свои таймауты

### Дашборды
- ⏳ Кнопки (Zigbee) — пока через legacy device triggers, не мигрированы

## Как работать

### Добавление новой группы света
1. Добавить в `manifests/leonid_house.yaml` → `features.lighting.groups`
2. `python3 tools/gen_helpers.py --apply`
3. `python3 tools/gen_dashboard_settings.py`
4. `pyscript.reload`

### Изменение логики контроллера
1. Редактировать `ha/pyscript/*.py`
2. `./tools/deploy.sh` (склеит в `/config/pyscript/manifest_loader.py`)
3. `pyscript.reload`

### Проверка работы
```bash
# Логи pyscript (фильтр: light, climate, vent)
tail -f /config/home-assistant.log | grep -E "\[light\]|\[climate\]|\[vent\]"

# Debug сервисы
```bash
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" -d '{}' \
  "$HA_URL/api/services/pyscript/light_debug"
```
## Известные проблемы
Mushroom cards
Требуют resources в configuration.yaml:

```yaml
lovelace:
  resources:
    - url: /hacsfiles/lovelace-mushroom/mushroom.js
      type: module
```

## Дубли helpers
Если в HA появились _2, _3:
```python3 tools/cleanup_helpers.py --manifest manifests/leonid_house.yaml --confirm```

## Shadow mode
При lighting_shadow_mode: on автоматика только логирует. Для реального управления:
```bash
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "input_boolean.lighting_shadow_mode"}' \
  "$HA_URL/api/services/input_boolean/turn_off"
  ```
## Следующие шаги
Party режим — не включать выключенное, держать включённое до рассвета
Keepalive table — motion_mode: keepalive в манифесте
Глобальные таймауты — input_number.motion_day_min, motion_night_min
Санузел — no_night_auto_flag, свои таймауты
Кнопки — мигрировать device triggers на event entity (sensor.*_action)

## Контакты
Манифест: manifests/leonid_house.yaml
Логи: /config/home-assistant.log
Pyscript: /config/pyscript/manifest_loader.py (склейка из ha/pyscript/*.py)
## СОСТОЯНИЕ НА 2026-08-24 (актуально, читать первым)
### Готово (сверх предыдущего)
- Party-роли: не включает выключенное, держит включённое до рассвета; роль на группу
- Keepalive table + глобальные таймауты движения + санузел (свои таймауты, запрет ночью)
- Фич-архитектура (4 артефакта); resolver; новый манифест (`features.groups`)
- `_lg_decide` = цепочка `_FD_CHAIN`; хелперы dusk/ct/imitation подключены
- Настройки по зонам; цельные карточки (vertical-stack-in-card)
### Следующие шаги: РЕФАКТОРИНГ
1. Реестр фич `_FD_REGISTRY` вместо жёсткого `_FD_CHAIN`
2. Единый `features.py`-словарь (schema+helpers+ui+decide в одной записи)
3. `tools/build_pyscript.py` вместо ручной склейки
4. Smoke-тест: diff `light_debug` до/после
