# SPEC: контракты платформы

## Слои
- Манифест (YAML) — источник правды инстанса: `instances/<id>/manifest.yaml`;
  runtime-копия `$HA_CONFIG/manifests/active.yaml`; секции под `features:`,
  группы света в `features.groups` с блоком `features:` у каждой группы.
- Feature-sliced: `features/{lighting,climate,ventilation,health}`; артефакты фичи:
  `schema` (resolve features→legacy), `helpers`, `ui`/`card`, `decide` (voters), `runtime`.
- Registry (`ha/pyscript/registry.py`) — runtime-реестр без Pydantic; строит `_REGISTRY`.
- Контроллеры (pyscript) — склейка `build/build_pyscript.py` в `/config/pyscript/manifest_loader.py`,
  порядок: registry → manifest_loader → features/{climate,ventilation,health}/runtime.py
  → features/lighting/decide.py → lighting_controller. Запуск: `./shp build` / `./shp deploy`.
- CLI `./shp`: validate | build | deploy | helpers | dashboards | check | cleanup | new feature|instance|group.

## Управление фичами
| Механизм | Влияние |
|---|---|
| `input_boolean.feature_<name>` (мастер и per-group) | выключает только автоматику; ручное работает всегда |
| FSM (`fsm_enabled: true` в манифесте) | автоматика использует конечный автомат для принятия решений |
| Ручное (vlight / кнопка-boolean / `vlight_toggle`) | всегда real: `_lg_manual_command` → `_lg_set_real(force=True)` |

## Vlight-контракт (освещение)
`vlight_<gid>` = командная шина группы; реальные лампы следуют за ней.
| Событие | Реакция |
|---|---|
| Решение автоматики (нет override) | пишет vlight под guard 10 с; лампы следуют (expected-guard 30 с, anti-cycle 2 мин) |
| vlight изменился без guard | ручная команда: override 60 мин на лампы + применение `force` (real даже в shadow) |
| Лампа изменилась без expected-guard | внешний manual: override 60 мин + синхронизация vlight |
| Override активен | автоматика не пишет ни vlight, ни лампы |
`override_timeout_min` (60), `anti_cycle_min` (2) — в манифесте.

## Таймауты движения
Глобально день/ночь: `input_number.motion_day_min`/`motion_night_min`;
санузел — свои (`motion_timeouts: own` → `light_<gid>_motion_day_min/_night_min`);
ночник — свой `light_<gid>_nightlight_off_min`.

## Select+time UI (расписание)
- `input_select.light_<gid>_on` СТРОГО `["Не включать", "Закат", "Время"]` — только расписание.
- `input_select.light_<gid>_off`: `["Время", "Рассвет", "Не выключать"]`.
- «Не включать» не блокирует датчик, если активен `motion_mode`.

## Датчик движения (ортогонален расписанию)
`input_select.light_<gid>_motion_mode`: `["Выкл", "Включать и выключать", "Держать включённым"]`.
- «Включать и выключать» (триггер; санузел, контейнер): `desired = presence`, если `dark or motion_day`;
  ночью при `no_night_auto_flag=on` и выключенном свете — не включать.
- «Держать включённым» (keepalive; стол): включён → держать пока `presence`, после таймаута выключить;
  выключен → решение за расписанием; ночью при `feature_<gid>_nightlight=on` — ночник.
- «Выкл» → датчик игнорируется.
Датчик: `input_select.light_<gid>_motion_sensor` — датчики той же `room` (live-чтение, fallback манифест).

## Ночник
Ночной профиль того же устройства (`light_<gid>_nightlight_brightness|r|g|b|off_min`).
Обычное включение после ночника восстанавливает дневной профиль (яркость + ct).

## Party
Роли на группу: `input_select.light_<gid>_party_role` —
`["Как обычно", "Включить", "Выключить", "Держать включённым"]`.
При `party_mode=on` решает роль; умолчание — держит включённое, выключенное не включает.

## Caps и профили устройств
- `caps: {dim|ct|rgb}` в группе — авто по `supported_color_modes` (dim = любой режим кроме `on_off`)
  + override манифестом. Сервис `pyscript.light_caps`, сенсор `sensor.light_caps` (атрибут `caps`).
- Applier: авто-включение = `turn_on` с параметрами активного профиля по caps
  (яркость + `color_temp_kelvin` из кривой); реле/без-цветных — голый on.
- UI по caps: яркость только при `dim`, ночник-палитра только при `rgb`
  (генераторы читают caps из HA; фолбэк «всё разрешено»).

## Decide
Voters регистрируются `@_fd_register` в `_FD_REGISTRY` (`features/lighting/decide.py`).
Приоритет = порядок регистрации:
party → «Не включать» → движение → manual_gate → окно выключения → время включения → закат.
`why` = имя победившей фичи; `_FD_ABORT` = группа пропускается (выключенный авто-флаг).

## Кнопки
Легаси device triggers (миграция на event-entity не взлетела — не повторять).
Кнопки тумблят boolean'ы/vlight'ы напрямую; платформа видит это как ручное управление.

## Дашборды (3 штуки, имена через дефис)
- `home-dashboard` (по комнатам), `settings-dashboard` (режимы/расписания),
  `admin-dashboard` (флаги/диагностика). Генерация: `./shp dashboards [home|settings|admin|all]`.
- Карточка группы — единый контейнер `custom:vertical-stack-in-card`
  (шаблон `features/lighting/card.py`); блоки фич сверху вниз (`features/lighting/ui.py`),
  условный рендер по подключённым фичам и caps.
- Mushroom и др. ресурсы — только в `configuration.yaml` (`lovelace: mode: yaml`).

## Сервисы pyscript
`manifest_reload/status/debug`, `light_debug`, `light_caps`, `light_override_clear`,
`vlight_toggle`, `climate_debug`, `vent_debug`, `override_status/clear`,
`sensor_health_status`, `feature_set_enabled`.
