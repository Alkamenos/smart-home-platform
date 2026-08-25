
## 3. CHANGELOG.md — последние изменения

```markdown
# Changelog
## 2026-08-25
### Добавлено
- CLI `./shp` (validate/build/deploy/helpers/dashboards/check/cleanup/new feature|instance|group)
- Feature-sliced: features/{lighting,climate,ventilation,health} (schema/helpers/ui/runtime)
- Реестр voters `_FD_REGISTRY` (`@_fd_register`); party-роли; keepalive; глобальные таймауты
- `instances/<id>/manifest.yaml`; `build/build_pyscript.py`; `core/{ha,manifest,builders}.py`
### Изменено
- Генераторы импортируют артефакты из features/; шимы, deploy.sh и gen_all_dashboards.sh удалены
### Известные проблемы
- Кнопки Zigbee — legacy device triggers (осознанно); helpers-оркестратор освещения в tools/gen_helpers.py

## 2026-08-25
### Добавлено
- CLI `./shp` (validate/build/deploy/helpers/dashboards/check/cleanup/new)
- Feature-sliced: `features/lighting/{schema,helpers,ui,card,decide}`
- `build/build_pyscript.py` (детерминированная склейка)
- `instances/<id>/manifest.yaml` (канонический манифест) + scaffold
- Party-роли, keepalive, глобальные таймауты, санузел-настройки, хелперы dusk/ct/imitation
### Изменено
- `_lg_decide` → цепочка `_FD_CHAIN`; генераторы читают `features.groups`

## 2026-08-24
### Добавлено
- Фич-архитектура: фича = 4 артефакта (schema/helpers/UI/decide)
- Новый формат манифеста: группы в `features.groups`, блок `features:` у группы;
  resolver `tools/resolve_features.py` (обратная совместимость)
- Party-роли per group (`input_select.light_<gid>_party_role`)
- Keepalive table: не включает выключенный днём, держит включённый N мин, ночью ночник
- Глобальные таймауты движения `motion_day_min|motion_night_min`
- Санузел: свои таймауты + запрет авто ночью
- Хелперы dusk/ct/imitation на карточке, подключены к контроллеру
- Настройки по зонам; цельная карточка группы `group_card.py`
### Изменено
- `_lg_decide` → цепочка voters `_FD_CHAIN`; `why` = имя фичи
### Известные проблемы
- Кнопки Zigbee — legacy device triggers (осознанно)
- Монолит manifest_loader.py ~1900 строк; voters в одном файле (рефакторинг)


## 2026-08-22

### Добавлено
- Три отдельных дашборда (home, settings, admin) через генераторы
- Dropdown выбор датчика движения per group (`input_select.light_*_motion_sensor`)
- Режим "Датчик движения" в `input_select.light_*_on`
- Ночник для table с RGB настройкой
- Мгновенная реакция на датчики движения через `@state_trigger`
- Система очистки дубликатов helpers (`cleanup_helpers.py`)
- Extended shadow logging с причиной решения

### Исправлено
- Feature/shadow семантика: ручное управление всегда работает в real
- Синтаксические ошибки при копировании (артефакты `ret urn`, пробелы)
- Mushroom cards не загружались (добавлены resources в configuration.yaml)
- Дубли helper'ов (`_2`, `_3`) при повторном запуске gen_helpers

### Изменено
- `_lg_decide` — добавлен `why` для расширенного логирования
- `_lg_set_real` — shadow блокирует только автоматику (force=False)
- `_lg_vlight_handler` — без блокировки по feature_lighting
- Дашборды разделены на 3 категории (повседневный, настройки, платформа)

### Известные проблемы
- Party режим включает весь свет вместо удержания включённого
- Table keepalive не реализован
- Глобальные таймауты движения отсутствуют
- Санузел: нет запрета авто-включения ночью
- Кнопки работают через device triggers, не мигрированы на event entity

## 2026-08-21

### Добавлено
- Освещение: 14 групп, vlight, auto/manual, motion
- Климат: 4 зоны, конвекторы, AC
- Вентиляция: 2× Vakio, рекуперация
- Манифест-ориентированная архитектура
- Генераторы helpers и дашбордов
- Override manager (60 мин lockout)