# ROADMAP платформы

Цели: стабильная и быстрая работа, low-code, AI-first, TDD, простота расширения и конфигурирования.
Приоритеты: P0 — критично/сейчас, P1-P4 — по мере готовности. Статусы: [ ] / [x].

## P0 — Стабильность
- [x] Регрессионные FSM-тесты + контракт дашборда + pytest в CI
- [x] Символьная проверка бандла при сборке (tools/check_bundle_symbols.py + CI)
- [x] Персист FSM-состояний между рестартами HA (fsm_engine)
- [x] Watchdog: расхождение FSM vs устройство, детектор зависших состояний (sensor_health)

## P1 — Системные фиксы поведения
- [ ] Generic debounce/hysteresis в fsm_engine (cooldown per trigger, лечение флэппинга системно)
- [x] YAML-сценарии как регрессии: features/*/scenarios/*.yaml + generic-раннер в pytest

## P2 — Low-code и прозрачность конфигурации
- [ ] `shplatform explain <id>` — резолвнутый конфиг + последнее решение FSM с why-цепочкой
- [ ] `shplatform provision --dry-run/--apply` — идемпотентные helpers из схемы манифеста
- [ ] Пресеты групп в схеме (outdoor_motion / garland_sunset / nightlight_wc)

## P3 — AI-first
- [ ] `pyscript.platform_doctor` — структурированный JSON-диагноз (FSM, расхождения, health, решения)
- [ ] `tools/gen_ai_context.py` — автогенерация актуального контекста (схемы+FSM+контракты+entities)
- [ ] NL -> manifest diff с гейтом `shplatform validate` + pytest в CI

## P4 — Простота расширения
- [ ] Конвенция фичи features/<name>/{schema,fsm,runtime,ui}.py + автоподключение
- [ ] `shplatform new-feature <name>` — каркас с примером FSM и тестом
- [ ] Snapshot-тесты дашбордов и property-тесты (hypothesis)
