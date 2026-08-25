# Правила pyscript (выстрадано практикой)

## Язык/склейка
- Нет общего namespace между файлами → склейка в один `/config/pyscript/manifest_loader.py`.
- Склейка = `build/build_pyscript.py`, ORDER: `ha/pyscript/registry.py` → `manifest_loader.py` →
  `features/{climate,ventilation,health}/runtime.py` → `features/lighting/decide.py` → `lighting_controller.py`.
- Generator expressions НЕ поддерживаются → только `[x for x in y]` и циклы.
- Избегать: вложенных функций в функциях, замыканий, `for k in dict` без `()`, `continue` в `@time_trigger`.
- Строки через `%` или `+` (f-строки не проверены).
- `@time_trigger("period=30")` не парсится → `@time_trigger("startup")` + `while True: task.sleep(30)`.
- `state.get()` бросает NameError при отсутствии сущности → безопасные обёртки (`_lg_state`).
- `climate.state` = hvac_mode, НЕ on/off.

## Деплой
- Править только исходники (`ha/pyscript/*.py`, `features/*/runtime.py`, `features/lighting/decide.py`), затем `./shp build` (py_compile внутри).
- `./shp deploy` = validate + build + копия манифеста в `$HA_CONFIG/manifests/active.yaml`.
- `pyscript.reload` дублирует фоновые циклы → после изменений логики только полный рестарт.
- Глобальный `@event_trigger("state_changed")` = перегрев → только целевые `@state_trigger`.

## Манифест/фичи
- Манифест инстанса: `instances/<id>/manifest.yaml`; runtime читает `$HA_CONFIG/manifests/active.yaml`.
- Группы света: `features.groups`; у группы блок `features:` (фичи) + опциональный `caps:`.
- Decide: voters регистрируются `@_fd_register` в `_FD_REGISTRY` (features/lighting/decide.py); приоритет = порядок регистрации; `why` = имя фичи.
- «Не включать» в расписании не гасит группы с активным датчиком (решает `_fd_motion`).
- Закат без темноты: `sun.sun` elevation < 0 (`_lg_update_dark` не трогать).

## Семантика управления (не нарушать!)
- Ручное ВСЕГДА в real: `force=True` обходит анти-цикл и блокировки; блокировки только для автоматики.
- `feature_*` выключают только автоматику; ручные команды по виртуальным флагам не блокируются мастер-флагом.
- Первый переключатель виртуального флага после рестарта съедается инициализацией состояния — тестировать вторым.
- Кнопки: только события `*_action`; НЕ device triggers и НЕ миграция на event-сущности.
- Ночник = профиль того же устройства; авто-включение всегда выставляет параметры профиля (яркость/цвет) — восстанавливает состояние после ночника.

## Артефакты копирования из чата
- Типовые поломки: пробелы внутри строк (`"unknown "`), `ret urn`, незакомментированные `====`-шапки, обрезанные строки. Лечится `py_compile`.
- Патчи из чата применять python-скриптом с `assert`-якорями и проверкой `s.count(old) == 1`.

## HA-специфика
- Коллизии имён → `_2/_3`; опции менять только через `input_select/set_options`; дубли чистить `./shp cleanup --confirm`.
- Удаление по websocket: пробовать `{"type": "<dom>/delete", "name": X}`, затем `"<dom>_id": X`.
- `state.set("sensor.x", ...)` создаёт виртуальный сенсор для дашборда.
- При `lovelace: mode: yaml` ресурсы только в `configuration.yaml`; имена файлов через дефис (`home-dashboard`).
