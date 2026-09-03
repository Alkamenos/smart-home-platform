# Smart Home Platform (Leonid's House)

Платформа умного дома на базе Home Assistant + pyscript + манифест-ориентированной архитектуры (feature-sliced).

## Архитектура

- **Манифест** (`instances/<id>/manifest.yaml`) — единый источник правды инстанса: устройства, группы света, фичи, зоны.
- **Фича = 4 артефакта**: `schema.py` (resolve), `helpers.py` (provisioning), `ui.py` (карточки), `decide.py` (voters); у контроллеров ещё `runtime.py`.
- **Runtime**: склейка в `/config/pyscript/manifest_loader.py` через `build/build_pyscript.py` (детерминированный порядок).
- **Семантика**: ручное ВСЕГДА в real; `feature_*` выключает только автоматику; анти-цикл + блокировка 60 мин после ручного вмешательства; источник команды распознаётся; FSM для принятия решений.

## Структура
```commandline
.platform/
├── shp, cli/ # CLI: validate/build/deploy/helpers/dashboards/check/cleanup/new
├── core/ # ha.py (REST+WS), manifest.py (instances/), builders.py
├── features/ # feature-sliced:
│ ├── lighting/ # schema, helpers, ui, card, caps, decide, state, control, runtime, services, triggers
│ ├── climate/ # runtime, helpers, ui
│ ├── ventilation/ # runtime, helpers, ui
│ └── health/ # runtime
├── build/ # build_pyscript.py — детерминированная склейка
├── instances/ # <id>/manifest.yaml — канонический манифест
├── ha/pyscript/ # registry.py, manifest_loader.py
├── tools/ # gen_helpers.py, gen_dashboard{home,settings,admin}.py, cleanup_helpers.py
└── *.md # README, PYSCRIPT_RULES, HANDOFF, CHANGELOG, ENTITY_PROVISIONING
```


## Установка

```bash
# 1. Клонировать в /config/.platform
cd /config && git clone <repo> .platform

# 2. Развернуть: валидация + склейка + копия манифеста в $HA_CONFIG/manifests/active.yaml
./shp deploy

# 3. Создать helpers (input_boolean, input_select, input_number, input_datetime)
./shp helpers --instance leonid_house --apply

# 4. Сгенерировать дашборды
./shp dashboards
```

## CLI команды

| Команда | Описание | Пример |
|---------|----------|--------|
| `validate` | Проверка манифеста на ошибки | `./shp validate` |
| `build` | Сборка pyscript файлов в один | `./shp build` |
| `deploy` | Валидация + сборка + копирование манифеста | `./shp deploy` |
| `helpers` | Создание вспомогательных сущностей (input_*) | `./shp helpers --instance leonid_house --apply` |
| `dashboards` | Генерация дашбордов из манифеста | `./shp dashboards` |
| `cleanup` | Удаление устаревших сущностей | `./shp cleanup --confirm` |
| `check` | Проверка состояния системы | `./shp check` |
| `new instance <id>` | Создание нового инстанса из шаблона | `./shp new instance my_house` |
| `new feature <id>` | Создание новой фичи (4 артефакта) | `./shp new feature irrigation` |
| `new group <gid>` | Сниппет группы для манифеста | `./shp new group garden_lights` |

**Флаги для `helpers`:**
- `--instance <name>` — имя инстанса (по умолчанию: leonid_house)
- `--manifest <path>` — путь к манифесту (альтернатива --instance)
- `--apply` — применить изменения (без флага — только preview)
- `--confirm` — подтвердить создание всех сущностей

**Рабочий процесс обновления:**
```bash
git pull
./shp build
./shp deploy
# Перезапуск Home Assistant
```

В configuration.yaml: pyscript: {allow_all_imports: true}, lovelace: с 3 дашбордами и ресурсами (mushroom + vertical-stack-in-card).
## Фичи

- Освещение (12 групп)
- Расписание: Закат / Время / Не включать + времена вкл/выкл и окно выключения
- Движение: режимы Выкл / Включать и выключать / Держать включённым — ортогонально расписанию; таймауты глобальные и свои (санузел + запрет авто ночью)
- Вечеринка: роли на группу (не включать выключенное; держать включённое до рассвета)
- Ночник = профиль того же устройства; после него авто-включение восстанавливает яркость/ct
- Возможности устройств (dim/ct/rgb): авто по supported_color_modes + override caps:; applier применяет только поддерживаемые параметры; контролы на карточке только по возможностям
- Имитация присутствия, цветовая температура по кривой день→ночь, сезонные варианты, подсветка выключателей, группы с tolerate_unavailable
- Климат (4 зоны) — конвекторы + AC, двунаправленная оценка, safety (зимний lockout AC с голосовым предупреждением, осушение летом, вентилятор санузла), координация с рекуператорами.
- Вентиляция (2× рекуператора) — пресеты приток/вытяжка/рекуперация, boost с авто-выключением, свободный нагрев/охлаждение, ночной/away, зимняя пауза, мок открытых дверей.
- Датчики — недоступность/батарейки со списком покупок; зоны на паузе при мёртвых датчиках.

## Диагностика
```
# Решения света + причины
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
-H "Content-Type: application/json" -d '{}' \
"$HA_URL/api/services/pyscript/light_debug"

# Возможности групп -> sensor.light_caps
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
-H "Content-Type: application/json" -d '{}' \
"$HA_URL/api/services/pyscript/light_caps"

# Сброс блокировок
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
-H "Content-Type: application/json" -d '{}' \
"$HA_URL/api/services/pyscript/override_clear"
```

## Логи:
Настройки → Журнал, фильтры [light], [climate], [vent], [health].

## Тиражирование и развитие
```
./shp new instance <id>   # новый инстанс из шаблона манифеста
./shp new feature <id>    # новая фича (4 артефакта)
./shp new group <gid>     # snippet группы для манифеста
```
