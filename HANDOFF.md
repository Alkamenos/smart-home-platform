Вот сжатый handoff-промт. Вставьте его в новый диалог — он содержит цель, архитектуру, текущее состояние, технические ограничения и следующие шаги.

---

# ПРОМТ: Возобновление проекта «Smart Home Platform» (Home Assistant)

## Цель
Строим **data-driven платформу умного дома** поверх Home Assistant как **продукт для тиражирования у заказчиков**. Ключевые требования: лёгкая модификация без монолита; миграция с легаси-автоматизаций без поломок; удобная настройка интервалов/режимов через UI; учёт внешних условий (не светить днём, не поливать в дождь); распознавание источника команды (физический выключатель / Алиса / автоматика) чтобы не конфликтовать с ручным управлением.

## Окружение
- HA на Raspberry Pi 4, доступ через веб + аддон VS Code (git). Репозиторий: `/config/.platform`.
- ZigBee через Zigbee2MQTT + Wi‑Fi устройства. Яндекс Станции.
- Устройства: конвекторы `switch.obogrevatel_{gostinnaia,sanuzel,spalnia,kabinet}`; тёплый пол = глобальный термостат `climate.termostat_gostinaia` (managed_by_platform=false); кондиционер AUX через ESPHome `climate.esphome_web_0d22a4_ac_name`; датчики `sensor.datchik_temperatury_{room}_temperature`; рекуператоры Vakio `fan.base_smart`, `fan.base_smart_2` (спальня/кабинет, ещё не подключены); выключатели Aqara H1M.
- Существующие helpers (переиспользуем, не создаём): `input_number.temperatura` (глобальный setpoint), `input_number.maksimalno_komfortnaia_temperatura` (порог охлаждения), `input_number.temperatura_v_sanuzle`, `input_boolean.zima` (сезон). Созданы: `input_boolean.feature_climate`, `input_boolean.climate_shadow_mode`.
- Легаси: автоматизация «Управление климатом» управляет конвекторами/рекуператорами/масляным радиатором; «Управление термостатом» синхронизирует setpoint→тёплый пол.

## Архитектура (принятые решения)
- **Манифест (YAML) = единый источник правды** инстанса. Pydantic-схема + валидатор (CLI, pre-deploy). Runtime-лоадер НЕ использует Pydantic (читает сырой dict).
- **Разделение**: HA-native (helpers, Lovelace) для UI; **pyscript** для логики.
- **Конкатенация**: pyscript изолирует файлы (нет общего namespace) → деплой склеивает `registry.py + manifest_loader.py + climate_orchestrator.py` в один `/config/pyscript/manifest_loader.py` (скрипт `deploy.sh`).
- **Climate Orchestrator**: polling ~30с; сезон из `input_boolean.zima`; heat/cool setpoints из input_number; deadband 0.5; safety min_setpoint=16; флаг `managed_by_platform`; режимы **shadow/real** через helper.
- **Override Manager (MVP)**: слушает `state_changed` управляемых устройств; если изменение не совпадает с недавней командой платформы → временный блок (`override_timeout_min`, умолч. 60).
- **Climate-устройства**: только конкретные режимы (cool/heat/off), никогда auto; команды только при переходе; уважение ручных правок.

## Критичные ограничения pyscript (выучены на ошибках)
- Нет общего namespace между файлами → конкатенация.
- Нет builtin `open` → `import builtins; builtins.open(...)`.
- Избегать `with` и `return` изнутри `with` (теряется значение).
- `@time_trigger("period=30")` не парсится → `@time_trigger("startup")` + бесконечный цикл с `task.sleep(30)`.
- После `pyscript.reload` могут остаться дубли фоновых циклов → **рекомендуется полный перезапуск HA**.
- Состояние `climate` = hvac_mode (cool/off/…), НЕ on/off → отдельная проверка `_clim_is_on`.

## Что ГОТОВО (работает)
- Часть A: схема+валидатор+CLI+тесты (зелёные). Часть B: лоадер в HA.
- Манифест `manifests/leonid_house.yaml`: 4 зоны (гостиная/санузел/спальня/кабинет).
- Дашборд Lovelace «Климат» (master-тумблер, shadow/real, уставки, статусы зон) + template-sensors в configuration.yaml.
- Climate Orchestrator (shadow проверен, real протестирован на кондиционере) + Override Manager (работает).
- Всё в git; `deploy.sh` (validate→concat→copy manifest).

## Следующие шаги (по порядку)
1. **Поэтапный real**: гостиная уже переведена (остальные конвекторы `managed_by_platform:false`); отключить блок «Гостинная» в легаси; наблюдать; затем по одной комнате.
2. Подключить **рекуператоры** как актуаторы (preset-режимы) и вентиляцию.
3. Фичи **освещение** и **полив** (с учётом внешних условий: люкс/дождь).
4. Расширить **Override Manager** (физ. выключатели H1M, голос Алиса) с приоритетами.
5. **Яндекс Диалоги** (голосовой интерфейс климата) — зарезервировано.
6. **Автогенерация дашборда** из манифеста (для тиражирования).

## Как продолжать
Репозиторий `/config/.platform`. Workflow: `shplatform validate manifests/leonid_house.yaml` → `./deploy.sh --ha-config /config` → полный перезапуск HA. Диагностика: сервисы `pyscript.manifest_status`, `pyscript.climate_debug`, `pyscript.override_status`; логи фильтр `[climate]`/`[override]`/`[manifest]`.

---
