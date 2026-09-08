# AI_CONTEXT — shplatform (leonid_house)

Декларативная платформа умного дома: манифест -> генерация pyscript-бандла,
хелперов и дашбордов. Все FSM-фичи собираются в ОДИН бандл ha/pyscript.

## Архитектура
- instances/leonid_house/manifest.yaml — единственный источник конфигурации
- features/<name>/{schema,state,decide,fsm,runtime}.py — модули фич (конкатенация)
- ha/pyscript/fsm_engine.py — универсальный FSM-движок (приоритеты, debounce, persist)
- build/build_pyscript.py — склейка бандла; tools/check_bundle_symbols.py — CI-чек
- shplatform/loader/registry.py — RuntimeRegistry: devices/features/groups
- cli/main.py (./shp) — validate/build/deploy/helpers/dashboards/explain/check

## Инварианты (не нарушать!)
- Приоритеты триггеров: manual > device_unavailable > schedule/sensor
- FSM-состояния публикуются в sensor.<entity>_fsm_state с атрибутами entered_by/why
- Каждое решение логируется в ring-buffer sensor.platform_decisions
- Ручное управление ставит MANUAL_LOCK; выход — по timeout/override_cleared
- pyscript НЕ поддерживает: generator expressions, comprehensions, walrus
- input_text в HA ограничен 255 символами (персист FSM — в файле)

## Фичи
- lighting: enabled=True
- sensor_health: enabled=True
- climate: enabled=True
- ventilation: enabled=True
- covers: enabled=True

## Группы света
- yard_floodlights (Улица/двор основное): lights=1
- street_night (Уличное ночное): lights=1
- office (Кабинет): lights=1
- office_lampa (Кабинет (настольная лампа)): lights=1
- office_kus (Кабинет (кусь)): lights=1
- bedroom (Спальня): lights=1
- living_room (Гостиная (подсветка зеркала)): lights=1
- guest_bedroom (Гостевая спальня (торшер)): lights=1
- kitchen_work (Кухня (рабочая поверхность)): lights=1
- table (Кухня (обеденный стол)): lights=1, motion=binary_sensor.datchik_dvizheniia_gostinnaia_occupancy
- container (Контейнер): lights=1, motion=binary_sensor.datchik_dvizheniia_konteiner_occupancy
- bathroom (Санузел): lights=1, motion=binary_sensor.vykliuchatel_sanuzel_presence
- garland_terrace (Гирлянда терраса): lights=1
- garland_street (Гирлянда уличная): lights=1
- garland_windows (Окна): lights=1
- xmas_a2 (Рождественская уличная): lights=1

## CLI
- ./shp validate|build|deploy|helpers --apply|dashboards|check|explain <id>
- ./shp explain <group_id> — разбор группы + live-статус

## Тесты
- python3 -m pytest tests/ -q (57 тестов: FSM-рег, сценарии, движок, персист)
- features/*/scenarios/*.yaml — YAML-регессии, generic-раннер tests/test_scenarios.py

## Диагностика в HA
- сервис pyscript.platform_doctor -> sensor.platform_doctor (JSON)
- админ-дашборд /admin-dashboard: вкладки Фичи/Диагностика/Датчики/Логирование
