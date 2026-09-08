# Lighting Feature — Документация для AI

## Назначение
Фича управления освещением на основе манифеста. Поддерживает 12+ групп света с различными профилями автоматизации.

## Архитектура файлов

```
features/lighting/
├── __init__.py       # Точка входа, экспорт FEATURE dict
├── schema.py         # Преобразование формата манифеста (new → legacy)
├── helpers.py        # Генерация input_* сущностей для UI
├── ui.py             # UI блоки для карточек групп
├── card.py           # Генерация полной карточки группы
├── caps.py           # Определение возможностей устройств (dim/ct/rgb)
├── decide.py         # Voters для принятия решений (FD_REGISTRY)
├── state.py          # Глобальные переменные состояния + хелперы чтения
├── control.py        # Управление реальными устройствами
├── runtime.py        # Главный цикл _lg_tick() + _lg_apply_group()
├── services.py       # Сервисы (light_debug, override_clear, vlight_toggle)
├── triggers.py       # Обработчики событий (кнопки, motion, vlight)
└── README.md         # Этот файл
```

## Ключевые концепции

### 1. vlight-слой
Виртуальные `input_boolean.vlight_<gid>` отделяют команду пользователя от физического исполнения.
- Команды приходят через vlight (дашборд, Алиса, кнопки)
- Состояние vlight синхронизируется с реальными лампами
- При ручном изменении реальных ламп — vlight обновляется

### 2. Override Manager
Блокировка автоматики после ручного вмешательства:
- Группы с датчиком движения: пауза 2-60 мин (настраивается)
- Группы без датчика: глобальная пауза 60 мин
- Флаг `manual_respect=off` отключает override для группы

### 3. Shadow Mode
Режим отладки: вместо исполнения команд — только логирование.
Включается через `input_boolean.lighting_shadow_mode`.

### 4. Profile Detection
Автоматическое определение профиля группы:
- `motion` — только датчик движения, нет расписания
- `manual_auto` — ручной переключатель авто через helper
- `dusk_till_dawn` — выключение на рассвет
- `dusk_till_time` — выключение по времени

## Фичи группы (features)

| Фича | Описание | Helpers |
|------|----------|---------|
| `schedule` | Расписание включения/выключения | on/off selectors, time pickers |
| `motion` | Датчик движения | sensor selector, mode, timeouts |
| `nightlight` | Ночник с RGB | brightness, color, timeout |
| `party` | Режим вечеринки | role selector |
| `dusk` | Ожидание темноты | require_dark toggle |
| `ct` | Цветовая температура | follow_global toggle |
| `imitation` | Имитация присутствия | participate toggle |

## Decide Voters (приоритет по порядку)

1. `_fd_party` — режим вечеринки
2. `_fd_ne_vkl` — селектор "Не включать"
3. `_fd_motion` — датчик движения
4. `_fd_manual_gate` — ручной шлагбаум для manual_auto
5. `_fd_off_window` — окно выключения
6. `_fd_on_time` — время включения
7. `_fd_dusk` — закат/темнота

## Runtime Flow

```
_lg_tick() (каждые 30 сек)
├── _lg_update_dark(cfg) — обнова статуса темноты
├── _lg_rebuild_light_map(cfg) — маппинг light→gid
└── для каждой группы:
    └── _lg_apply_group(g, cfg, mode)
        ├── _lg_handle_vlight_change() — реакция на смену vlight
        ├── _lg_track_real() — детект ручного вмешательства
        ├── _lg_decide() — решение от voters
        └── _lg_set_real() — применение к устройствам
```

## Глобальные переменные (state.py)

| Переменная | Назначение |
|------------|------------|
| `_LG_PREV` | Предыдущее состояние ламп (для детекта изменений) |
| `_LG_OVERRIDE` | Блокировки по entity (timestamp) |
| `_LG_LAST_CHANGE` | Время последнего изменения (anti-cycle) |
| `_LG_MOTION_LAST` | Последнее движение по gid |
| `_DARK` | Статус темноты (с гистерезисом) |
| `_VLIGHT_PREV` | Предыдущее состояние vlight |
| `_EXPECTED_REAL_STATE` | Ожидаемое состояние (для фильтра команд платформы) |
| `_LG_NL_ACTIVE` | Лампы в режиме ночника |
| `_RGB_APPLIED` | Применённые RGB сцены |
| `_CT_LAST` | Время последней смены CT |
| `_LG_IM_ACTIVE` | Активная имитация присутствия |
| `_BUTTON_MAP` | Маппинг кнопок → действия |

## Важные ограничения Pyscript

⚠️ **Нет общего namespace между файлами** — все глобальные переменные объявляются в `state.py` и импортируются.
⚠️ **`@time_trigger("period=30")` не работает** — используется `@time_trigger("startup")` + цикл с `task.sleep(30)`.
⚠️ **Генератор-выражения не поддерживаются** — только list comprehensions.
⚠️ **После изменений логики — полный перезапуск HA** (pyscript.reload дублирует циклы).

## API для других модулей

```python
from features.lighting import caps
caps.group_caps(group)  # -> {"dim": True, "ct": False, "rgb": True}

from features.lighting.schema import resolve_group, _feats_of
resolved = resolve_group(raw_group)  # new format → legacy
feats = _feats_of(group)  # получить фичи группы
```

## Точки расширения

Для добавления новой фичи:
1. Добавить voter в `decide.py` с декоратором `@_fd_register`
2. Добавить helpers в `helpers.py` (функция `helpers_<name>`)
3. Добавить UI блок в `ui.py` (функция `ui_<name>`)
4. Обновить `FEATURE_ORDER` в `helpers.py` и `ui.py`

---

## Troubleshooting

### Ошибка `ModuleNotFoundError: No module named 'features'`

**Симптом:**
```
ModuleNotFoundError: No module named 'features'
  File "/config/pyscript/manifest_loader.py", line ..., in file.manifest_loader
    from features.lighting.state import (...)
```

**Причина:**
Pyscript выполняет код в изолированном контексте. Если файл фичи (например, `features/lighting/state.py`) импортируется другими модулями этой же фичи, но в нём не объявлены переменные/функции, которые ожидаются при импорте, возникает ошибка на уровне всего пакета `features`.

В нашем случае проблема возникла потому, что `decide.py` импортировал из `state.py` переменные `_FD_REGISTRY` и `_FD_ABORT`, которые не были объявлены в `state.py` после рефакторинга.

**Решение:**
Убедитесь, что все символы (публичные и приватные), которые экспортируются из модуля и используются другими модулями фичи, явно объявлены в этом модуле.

Пример исправления:
```python
# features/lighting/state.py

# Было (ошибка):
# _FD_REGISTRY и _FD_ABORT отсутствовали, но импортировались в decide.py

# Стало (исправлено):
_FD_REGISTRY = []  # Реестр fade-задач
_FD_ABORT = {"abort": True}  # Флаг для прерывания задач
```

**Профилактика:**
1. После рефакторинга всегда запускайте сборку: `python build/build_pyscript.py`
2. Проверяйте, что все импорты в пределах фичи разрешаются
3. Используйте явные объявления всех глобальных переменных в модуле состояния
4. При добавлении нового модуля проверяйте его зависимости от других модулей фичи
5. Сверяйте импорты в начале каждого файла с фактически определёнными именами
