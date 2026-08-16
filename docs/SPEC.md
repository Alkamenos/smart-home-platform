# SPEC: контракты платформы

## Слои
- **Манифест (YAML)** — источник правды инстанса; секции под `features:`.
- **Схема (Pydantic, `shplatform/schema/`)** — только валидация CLI; `FeaturesConfig`
  с `extra="forbid"`, модели фич с `extra="allow"`.
- **Runtime-лоадер** — читает манифест без Pydantic, строит `_REGISTRY`.
- **Контроллеры (pyscript)** — см. docs/PYSCRIPT_RULES.md.

## Управление фичами
- Мастер-флаг фичи (`input_boolean.feature_<name>`), глобальный shadow
  (`input_boolean.lighting_shadow_mode`), пер-групповой `shadow: true` в манифесте,
  пер-групповой `feature_flag`. Shadow = только логи `[SHADOW]`, без команд.

## Vlight-контракт (освещение)
vlight = командная шина группы. Реальные лампы следуют за vlight.

| Событие | Реакция платформы |
|---|---|
| Решение автоматики (override нет) | пишет vlight под guard 10 c; лампы следуют (expected-guard 30 c, anti-cycle 2 мин) |
| vlight изменился без guard (UI/Алиса/кнопка-через-boolean) | ручная команда: override 60 мин на лампы группы + применение force |
| Лампа изменилась без expected-guard (физ. выключатель/легаси) | внешний manual: override 60 мин + синхронизация vlight с фактом |
| Override активен | автоматика не пишет vlight и не командует лампы |

- `override_timeout_min` (default 60), `anti_cycle_min` (default 2) — в манифесте.
- Select+time UI: `Не включать` → desired=False; `Время` → desired = now>=T; иначе профиль.
- Сервисы: `pyscript.light_debug`, `pyscript.light_override_clear`, `pyscript.vlight_toggle`.

## Кнопки
Z2M `operation_mode: event` не трогать. Легаси-автоматизации кнопок тумблят boolean'ы;
при миграции группы target автоматизации перенаправляется на `vlight_<id>` —
кнопка становится ручным входом платформы без нового кода.
Прямое прослушивание (секция `lighting.buttons` + `@state_trigger`) — future.

## Миграция легаси (playbook на группу)
1. Создать helpers (gen_helpers.py). 2. Включить `feature_flag` (группа под платформой).
3. В тот же момент отключить легаси-синхронизацию «boolean→свет» группы.
4. Кнопочные легаси-автоматизации перенаправить на `vlight_<id>`.
5. Проверить `tools/deploy.sh --smoke` и поведение на закате/рассвете.
