## ⚡ АКТУАЛЬНО — 2026-08-25 (читать первым)
Рефакторинг завершён: FSD-структура `features/{lighting,climate,ventilation,health}`,
CLI `./shp` (validate|build|deploy|helpers|dashboards|check|cleanup|new feature|instance|group),
`build/build_pyscript.py`, манифест в `instances/<id>/manifest.yaml` (группы в `features.groups`),
`core/{ha,manifest,builders}.py`, реестр voters `_FD_REGISTRY` (@_fd_register).

Освещение (сверх базовых фич):
- ✅ Режим Party — роли per group (`light_<gid>_party_role`), не включает выключенное
- ✅ Keepalive (table) — `motion_mode: keepalive`
- ✅ Глобальные таймауты `motion_day_min|motion_night_min`; санузел — свои + `no_night_auto`
- ✅ Caps dim/ct/rgb: авто по `supported_color_modes` + override `caps:` в манифесте
  (сервис `pyscript.light_caps`, сенсор `sensor.light_caps`)
- ✅ Applier: явные brightness+ct при авто-on, восстановление после ночника
- ✅ `light_<gid>_motion_mode` (Выкл/Включать и выключать/Держать включённым) —
  расписание и датчик ортогональны; «Датчик движения» убран из `light_<gid>_on`
- ✅ UI по caps: яркость только для диммируемых, ночник-RGB только для RGB

Дальше: продуктовые фичи (сопровождение, полив), второй инстанс, кнопки, Яндекс-диалоги.

---
