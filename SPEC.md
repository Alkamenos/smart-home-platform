# SPEC: контракты платформы

## Слои
- **Манифест (YAML)** — источник правды инстанса; секции под `features:`.
- **Registry** (`registry.py`) — runtime-реестр без Pydantic/HA; строит `_REGISTRY`.
- **Runtime-лоадер** (`manifest_loader.py`) — читает манифест, сервисы `manifest_*`.
- **Контроллеры (pyscript)** — склеиваются deploy.sh в `/config/pyscript/manifest_loader.py`,
  порядок: registry → manifest_loader → climate → ventilation → sensor_health → lighting.
- **Генераторы** — `tools/gen_helpers.py`, `tools/gen_dashboard_*.py`, `tools/cleanup_helpers.py`.

## Управление фичами (семантика v2)
| Механизм | Влияние |
|---|---|
| `input_boolean.feature_<name>` (мастер и per-group) | выключает **только автоматику**; ручное управление работает всегда |
| `input_boolean.<name>_shadow_mode` | автоматика **только логирует** `[SHADOW]` с причиной (`why`); ручное работает в real |
| per-group `shadow: true` в манифесте | то же для одной группы |
| Ручное (vlight/кнопка-boolean/`vlight_toggle`) | **всегда real**: `_lg_manual_command` → `_lg_set_real(force=True)` обходит shadow |

## Vlight-контракт (освещение)
vlight = командная шина группы. Реальные лампы следуют за vlight.
| Событие | Реакция |
|---|---|
| Решение автоматики (override нет) | пишет vlight под guard 10 с; лампы следуют (expected-guard 30 с, anti-cycle 2 мин) |
| vlight изменился без guard | ручная команда: override 60 мин на лампы + применение **force (real даже в shadow)** |
| Лампа изменилась без expected-guard | внешний manual: override 60 мин + синхронизация vlight |
| Override активен | автоматика не пишет vlight и не командует лампы |

`override_timeout_min` (60), `anti_cycle_min` (2) — в манифесте.
Таймауты ручного override: глобально день/ночь = `input_number.motion_day_min` / `motion_night_min`;
санузел — свои (`motion_timeouts: own` → `light_<gid>_motion_day_min/_night_min`); ночник — свой `light_<gid>_nightlight_off_min`.

## Select+time UI
`input_select.light_<gid>_on` опции СТРОГО: `["Не включать", "Закат", "Время", "Датчик движения"]`.
`input_select.light_<gid>_off`: `["Время", "Рассвет", "Не выключать"]`.

## Motion-режимы (sel_on = «Датчик движения»)
- **trigger** (default; санузел, контейнер): `desired = presence`, если `dark or motion_day`.
- **keepalive** (`motion_mode: keepalive`; стол):
  - свет включён → держать, пока presence; выключить после N мин без движения;
  - свет выключен днём → **не включать**;
  - свет выключен ночью (`vecher`) и `feature_<gid>_nightlight=on` → **ночник** (brightness/RGB из helpers).
- **Ночной запрет авто** (санузел): `no_night_auto_flag` + `vecher=on` + свет выключен → не включать.
- **Dropdown датчика**: `input_select.light_<gid>_motion_sensor`, опции — датчики той же `room`
  (меняется без рестарта; контроллер читает helper, fallback — манифест).
- **Party mode**: не включает выключенное; включённое держит до рассвета (`dark and any_on`).

## Кнопки
**Решение: остаются легаси-автоматизации (device triggers).** Миграция на event-entity
(`sensor.*_action`, `legacy_triggers: false`) не взлетела — не повторять. Кнопки тумблят
boolean'ы/vlight'ы напрямую, платформа видит это как ручное управление.

## Дашборды (3 штуки, имена через дефис)
- `home-dashboard` — повседневный, карточки по комнатам (mushroom cards).
- `settings-dashboard` — режимы, расписания, motion, ночник, датчики.
- `admin-dashboard` — feature-флаги, shadow, диагностика.
Генераторы: `gen_dashboard_home/settings/admin.py` + `gen_all_dashboards.sh`.
**Mushroom**: при `lovelace: mode: yaml` ресурсы объявляются в `configuration.yaml`
(`lovelace.resources`), HACS-UI ресурсы не применяются.

## Сервисы pyscript
`manifest_reload/status/debug`, `light_debug`, `light_override_clear`, `vlight_toggle`,
`climate_debug`, `vent_debug`, `override_status/clear`, `sensor_health_status`, `feature_set_enabled`.