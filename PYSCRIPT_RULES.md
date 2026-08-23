# Правила pyscript (выстрадано практикой)

## Язык/AST
- Нет общего namespace → склейка в один файл (порядок: registry → manifest_loader → climate →
  ventilation → sensor_health → lighting).
- Generator expressions НЕ поддерживаются → только list comprehension `[x for x in y]` и циклы.
- Dict comprehension и вложенные def/closure — избегать.
- Строки через `%` или `+` (f-строки не проверены).
- `@time_trigger("period=30")` не парсится → `@time_trigger("startup")` + `while True: task.sleep(30)`.
- `state.get()` бросает NameError при отсутствии сущности → безопасные обёртки (`_lg_state`).
- `climate.state` = hvac_mode, НЕ on/off.

## Деплой
- `/config/pyscript/manifest_loader.py` — **генерируемая склейка**; править только исходники
  `ha/pyscript/*.py` + `./tools/deploy.sh` (иначе правки затрутся).
- После правок: `python3 -m py_compile` ДО reload.
- `pyscript.reload` дублирует фоновые циклы → для циклов только полный рестарт HA.
- Глобальный `@event_trigger("state_changed")` = перегрев → только целевые `@state_trigger`.

## Артефакты копирования из чата
- Типовые поломки: пробелы внутри строк (`"unknown "`), `ret urn`, незакомментированные `====`-шапки,
  обрезанные строки. Лечится `tools/fix_artifacts.py` + `py_compile`.
- Патчи из чата применять python-скриптом с `assert`-якорями и проверкой `s.count(old) == 1`.

## HA-специфика
- Helpers: коллизия имён → суффиксы `_2/_3`; обновление опций только через `set_options`;
  чистка дублей `cleanup_helpers.py`. Websocket-delete: пробовать `name` и `<dom>_id`.
- `state.set("sensor.x", ...)` создаёт виртуальный sensor для дашборда.
- Mushroom при `lovelace: mode: yaml` — ресурсы только в `configuration.yaml`.
- Имена дашбордов/файлов — через дефис (`home-dashboard`).

## Семантика управления (не нарушать!)
- Ручное ВСЕГДА real: `_lg_set_real(..., force=True)` обходит shadow; shadow блокирует только
  автоматику (`mode == "shadow" and not force`).
- feature-флаги выключают только автоматику; `_lg_vlight_handler` НЕ блокируется мастер-флагом.
- Первый toggle vlight после рестарта съедается инициализацией `_VLIGHT_PREV` — тестировать вторым.
- Кнопки Zigbee: легаси device triggers, НЕ мигрировать на event-entity (сломает автоматизации).