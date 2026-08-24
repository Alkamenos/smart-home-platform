# Provisioning helper-сущностей

Генератор: `python3 tools/gen_helpers.py --manifest manifests/leonid_house.yaml [--apply] [--orphan] [--delete --confirm]`.

## Конвенция имён (строго)
Per group (`<gid>` из манифеста):
- `input_boolean.vlight_<gid>` — командная шина
- `input_select.light_<gid>_on` — `["Не включать", "Закат", "Время", "Датчик движения"]`, initial `Закат`
- `input_select.light_<gid>_off` — `["Время", "Рассвет", "Не выключать"]`, initial `Время`
- `input_datetime.light_<gid>_on_time|off_time|off_end_time` — `has_date: false, has_time: true`
- `input_number.light_<gid>_brightness` (1–100)
- `input_boolean.feature_<gid>` (on)
- если `motion_sensor`: `input_select.light_<gid>_motion_sensor` (опции = датчики той же `room`),
  `light_<gid>_motion` (on), `light_<gid>_motion_day` (off),
  `light_<gid>_motion_day_min` (5), `light_<gid>_motion_night_min` (2)
- если `nightlight`: `feature_<gid>_nightlight` (off), `light_<gid>_nightlight_brightness|off_min|r|g|b`
- если `no_night_auto_flag`: соответствующий boolean (off)

Глобальные: `motion_day_min|motion_night_min`, `ct_day_kelvin|ct_night_kelvin`,
`ct_warm_from|ct_night_from`, `feature_rgb`, `light_rgb_scene`, `feature_lighting`,
`lighting_shadow_mode`, `feature_color_temp|backlight|imitation`, `imitation_start|end`;
climate: `feature_climate`, `climate_shadow_mode`, setpoints зон, `vlazhnost_v_dome`;
ventilation: `feature_ventilation`, `ventilation_shadow_mode`, флаги;
globals: `zima`, `vecher`, `my_doma`, `party_mode`;
плюс `feature_<fname>` и `<fname>_shadow_mode` для каждого ключа `features:`.

## Правила обновления (важно!)
1. **HA создаёт `_2`, `_3` при коллизии object_id.** Никогда не «пересоздавай» для обновления:
   - опции select'ов меняй через `input_select/set_options`;
   - дубли чисти `tools/cleanup_helpers.py --confirm` (удаляет `_[2-9]` и boolean-мусор).
2. **Websocket-удаление helper'а**: параметр зависит от версии HA — пробовать
   `{"type": "<dom>/delete", "name": X}`, затем `"<dom>_id": X`.
3. `--apply` создаёт только отсутствующие; `--orphan` / `--delete --confirm` — чистка вне манифеста
   (whitelist: `zima`, `vecher`, `my_doma`, `party_mode`).
4. После provisioning: перегенерировать дашборды, полный рестарт HA (не `pyscript.reload` —
   дублируются фоновые циклы).
если фича party (всегда): `input_select.light_<gid>_party_role`
(Как обычно/Включить/Выключить/Держать включённым)
если фича dusk: `input_boolean.light_<gid>_require_dark`
если фича ct: `input_boolean.light_<gid>_ct_follow`
если фича imitation: `input_boolean.light_<gid>_imitation`
