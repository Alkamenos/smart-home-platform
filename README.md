# Smart Home Platform (Leonid's House)

Платформа умного дома на базе Home Assistant + pyscript + манифест-ориентированной архитектуры.

## Архитектура

### Компоненты
- **Манифест** (`manifests/leonid_house.yaml`) — декларативное описание устройств, фич, зон
- **Registry** (`registry.py`) — runtime-реестр, строит структуры из манифеста
- **Контроллеры** (pyscript):
  - `lighting_controller.py` — освещение (14 групп, motion, nightlight, RGB)
  - `climate_orchestrator.py` — климат (4 зоны, конвекторы, AC)
  - `ventilation_controller.py` — вентиляция (2× Vakio, рекуперация)
  - `sensor_health.py` — мониторинг датчиков и батареек
- **Дашборды** (Lovelace YAML):
  - `home-dashboard.yaml` — повседневный (по комнатам)
  - `settings-dashboard.yaml` — настройки (свет, климат, вентиляция)
  - `admin-dashboard.yaml` — платформа (фичи, диагностика)

### Фичи
- **Освещение**: vlight + auto/manual режимы, motion с таймаутами, ночник, RGB, имитация присутствия
- **Климат**: зонное управление, сезонное поведение, safety (lockout AC зимой, осушение)
- **Вентиляция**: рекуперация, free heating/cooling, boost режимы, вентилятор санузла
- **Датчики движения**: мгновенная реакция через `@state_trigger`, dropdown выбор датчика
- **Override**: 60-минутный lockout после ручного вмешательства

## Установка

```bash
# 1. Клонировать в /config/.platform
cd /config
git clone <repo> .platform

# 2. Развернуть pyscript
./tools/deploy.sh

# 3. Создать helpers
python3 tools/gen_helpers.py --manifest manifests/leonid_house.yaml --apply

# 4. Сгенерировать дашборды
./tools/gen_all_dashboards.sh
```
# 5. Добавить в configuration.yaml:
# - pyscript: (см. docs/setup.md)
# - lovelace: (с dashboards и resources)
# - mushroom cards resources

## Использование
# Переключение feature/shadow
feature_* — включает/выключает автоматику (ручное всегда работает)
shadow — автоматика только логирует, не исполняет (ручное работает в real)
# Диагностика
```bash
# Light debug
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" -d '{}' \
  "$HA_URL/api/services/pyscript/light_debug"

# Override clear
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" -d '{}' \
  "$HA_URL/api/services/pyscript/override_clear"
```
## Движение
- Датчик срабатывает → мгновенный @state_trigger → _lg_apply_group
- Ночник: feature_<gid>_nightlight=on + vecher=on + sel_on="Датчик движения"

## Troubleshooting


## Структура (актуально 2026-08-25)
.platform/
├── shp, cli/          # CLI: validate/build/deploy/helpers/dashboards/check/cleanup/new
├── core/              # ha.py (REST+WS), manifest.py (instances/), builders.py
├── features/          # feature-sliced слайсы:
│   ├── lighting/      # schema, helpers, ui, card, decide (_FD_REGISTRY)
│   ├── climate/       # runtime, helpers, ui
│   ├── ventilation/   # runtime, helpers, ui
│   └── health/        # runtime
├── build/             # build_pyscript.py — детерминированная склейка
├── instances/         # <id>/manifest.yaml — канонический манифест
├── ha/pyscript/       # registry, manifest_loader, lighting_controller
├── tools/             # gen_helpers, gen_dashboard_{home,settings,admin}, cleanup_helpers
└── docs + *.md        # README, PYSCRIPT_RULES, HANDOFF, CHANGELOG, ENTITY_PROVISIONING

Фича = 4 артефакта (schema/helpers/ui/decide).
Новая фича: `./shp new feature <id>`; новое место: `./shp new instance <id>`; группа: `./shp new group <gid>`.
