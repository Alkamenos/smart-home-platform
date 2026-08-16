# Правила pyscript (выстрадано практикой)

1. **Нет общего namespace** между файлами → все контроллеры склеиваются в один файл,
   порядок: registry → manifest_loader → climate → ventilation → sensor_health → lighting.
2. **Generator expressions НЕ поддерживаются** (`not implemented ast ast_generatorexp`):
   запрещено `(x for x in y)` в любом контексте: `any()`, `all()`, `sum()`, `join()`, `sorted()`...
   Разрешено: list comprehension `[x for x in y]` и обычные циклы.
   Sanity-проверка встроена в `tools/deploy.sh`.
3. **`state.get(entity)` бросает NameError**, если сущности нет!
   Читать только через безопасную обёртку (паттерн `_lg_state`/`_lg_attr`):
   `st = hass.states.get(entity); return None if st is None else st.state`.
4. `@time_trigger("period=30")` не парсится → `@time_trigger("startup")` + `while True: task.sleep(30)`.
5. После `pyscript.reload` дублируются фоновые циклы → **только полный перезапуск HA**.
6. Глобальный `@event_trigger("state_changed")` = спам/перегрев на RPi4 →
   только целевые `@state_trigger` по явному списку entity.
7. `climate.state` = hvac_mode (cool/off/...), НЕ on/off.
8. Dict comprehension и вложенные def/closure — не проверены, избегать до проверки.
   Строки собирать через `%` или `+` (f-строки не проверены).
9. Кнопки Zigbee в режиме Z2M `operation_mode: event` не имеют активного action-entity
   (entity отключён, device trigger работает напрямую через MQTT). Не переключать режим —
   легаси-автоматизации сломаются.
