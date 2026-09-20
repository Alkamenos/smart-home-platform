# 📋 Промпт для Qwen Coder: Редактирование манифеста в WebUI

Скопируй и используй этот промпт для работы с Qwen Coder:

---

## 🎯 РОЛЬ И КОНТЕКСТ

Ты — senior Python разработчик, работающий над проектом **Smart Home Platform V3**. Платформа управляет умным домом через FSM (конечные автоматы) и интегрируется с Home Assistant.

**Текущее состояние WebUI:**
- ✅ FastAPI приложение в `src/webui/app.py`
- ✅ Pydantic модели в `src/webui/models.py` (уже соответствуют реальной структуре манифеста)
- ✅ Jinja2 шаблоны в `src/webui/templates/`
- ✅ HTMX для динамических обновлений без JavaScript
- ✅ Bootstrap 5 (dark theme) для стилей
- ✅ Манифест **отображается** корректно (Leonid's House, 4 комнаты, устройства, behaviors)
- ❌ Манифест **НЕ редактируется** — только read-only view

**Структура проекта:**
```
src/webui/
├── app.py              # FastAPI приложение, create_app()
├── models.py           # Pydantic модели (InstanceConfig, RoomConfig, DeviceConfig, BehaviorConfig, etc.)
├── routes.py           # Дополнительные роуты
├── __init__.py
└── templates/
    ├── index.html      # Главная страница (уже работает)
    ├── health.html     # Healthcheck
    └── partials/       # HTMX-фрагменты
```

---

## 🎯 ЗАДАЧА

Добавить **полноценное редактирование манифеста** через WebUI. После реализации пользователь должен иметь возможность:

1. **Inline-редактирование** всех полей манифеста прямо на странице
2. **CRUD операции** для:
   - Комнат (rooms): добавить, редактировать, удалить
   - Устройств (devices): добавить, редактировать, удалить в рамках комнаты
   - Поведений (behaviors): добавить, редактировать, удалить в рамках устройства
   - Сенсоров (sensors): добавить, редактировать, удалить для комнаты
3. **Автосохранение** изменений в YAML файл (`instances/leonids_house/manifest.yaml`)
4. **Валидация** через Pydantic перед сохранением
5. **Откат изменений** (undo) — минимум 1 уровень
6. **Визуальная обратная связь** — подсветка изменённых полей, индикаторы сохранения

---

## 🔧 ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ

### Архитектура
- **HTMX** для всех динамических операций (без написания JS)
- **HTMX_swap** для плавных обновлений
- **Bootstrap 5 modals** для сложных форм редактирования
- **Server-side rendering** через Jinja2 partials

### API Endpoints (добавить/расширить)

```python
# Комнаты
GET / rooms / {room_id} / edit  # Форма редактирования комнаты (HTMX fragment)
POST / rooms / {room_id} / update  # Обновить комнату
POST / rooms / add  # Создать новую комнату
DELETE / rooms / {room_id}  # Удалить комнату

# Устройства
GET / rooms / {room_id} / devices / {device_id} / edit
POST / rooms / {room_id} / devices / {device_id} / update
POST / rooms / {room_id} / devices / add
DELETE / rooms / {room_id} / devices / {device_id}

# Поведения
GET / rooms / {room_id} / devices / {device_id} / behaviors / {behavior_id} / edit
POST / rooms / {room_id} / devices / {device_id} / behaviors / {behavior_id} / update
POST / rooms / {room_id} / devices / {device_id} / behaviors / add
DELETE / rooms / {room_id} / devices / {device_id} / behaviors / {behavior_id}

# Общие
POST / save  # Сохранить весь манифест (уже есть, но доработать)
GET / manifest / raw  # Получить raw JSON манифеста
POST / manifest / reload  # Перезагрузить манифест из файла (откатить изменения)
```

### Работа с данными
- Все изменения применяются к **in-memory** объекту `ManifestModel`
- Сохранение в YAML происходит **только** при нажатии "Save Manifest"
- Использовать `yaml.dump(..., default_flow_style=False, sort_keys=False)` для сохранения читаемого формата
- **Backup** перед сохранением: создавать `manifest.yaml.bak` с timestamp

### Формы и валидация
- Использовать **Pydantic validation** при каждом обновлении
- Ошибки валидации возвращать как **Bootstrap alert** через HTMX
- Все поля формы должны иметь соответствующие input types:
  - `int` → `<input type="number">`
  - `bool` → `<input type="checkbox">`
  - `str` → `<input type="text">`
  - `dict[str, Any]` (params в behavior) → JSON-редактор или key-value пары
  - `schedule` (строка "23:00-07:00") → time-range picker

---

## 📝 ПОШАГОВЫЙ ПЛАН РЕАЛИЗАЦИИ

### Шаг 1: Подготовка (models.py)
- Убедиться что все модели имеют `model_config = {"extra": "allow"}` для гибкости
- Добавить методы `.to_dict()` для сериализации (если нужны)
- Проверить что `InstanceConfig`, `RoomConfig`, `DeviceConfig`, `BehaviorConfig` полностью покрывают структуру

### Шаг 2: Refactor `app.py` — добавить состояние
- Добавить **in-memory хранилище** текущего манифеста (singleton):
  ```python
  class ManifestStore:
      def __init__(self, path: str):
          self.path = path
          self.current: ManifestModel | None = None
          self.backup: ManifestModel | None = None

      def load(self): ...
      def save(self): ...
      def revert(self): ...


  manifest_store = ManifestStore(manifest_path)
  ```
- Переделать `index()` чтобы использовать `manifest_store.current`
- Все update-роуты должны модифицировать `manifest_store.current`

### Шаг 3: Создать partials (HTMX-фрагменты)
```
templates/partials/
├── room_form.html          # Форма редактирования комнаты
├── device_form.html        # Форма редактирования устройства
├── behavior_form.html      # Форма редактирования поведения
├── room_card.html          # Переиспользуемая карточка комнаты (для HTMX swap)
├── device_item.html        # Элемент устройства
├── save_success.html       # Сообщение об успехе (уже есть)
└── save_error.html         # Сообщение об ошибке (уже есть)
```

### Шаг 4: Обновить `index.html`
- Заменить статичные `<div class="device-item">` на HTMX-интерактивные элементы
- Добавить кнопки Edit/Delete для каждого элемента
- Пример:
  ```html
  <div class="device-item" id="device-{{ device.id }}">
      <h6>{{ device.id }}
          <span class="badge bg-secondary">{{ device.type }}</span>
          <button hx-get="/rooms/{{ room.id }}/devices/{{ device.id }}/edit"
                  hx-target="#edit-modal-content"
                  data-bs-toggle="modal"
                  data-bs-target="#editModal"
                  class="btn btn-sm btn-outline-primary ms-2">
              ✏️
          </button>
          <button hx-delete="/rooms/{{ room.id }}/devices/{{ device.id }}"
                  hx-target="#device-{{ device.id }}"
                  hx-swap="outerHTML"
                  hx-confirm="Удалить устройство?"
                  class="btn btn-sm btn-outline-danger ms-1">
              🗑️
          </button>
      </h6>
      ...
  </div>
  ```

### Шаг 5: Реализовать endpoints в `routes.py` или `app.py`
- Использовать `Form(...)` из FastAPI для приёма данных форм
- Возвращать **HTML-фрагменты** (partial templates) для HTMX swap
- Обрабатывать `HX-Request` header для определения типа ответа

### Шаг 6: Редактор для `params` (dict[str, Any])
- Создать виджет для редактирования key-value пар
- Или использовать JSON-textarea с валидацией
- Популярные параметры (`brightness`, `motion_timeout_sec`, `schedule`) должны иметь **dedicated controls**

### Шаг 7: Indicators и UX
- Добавить badge "Unsaved changes" в navbar когда есть изменения
- Подсветка изменённых полей (CSS class `.modified`)
- Toast-уведомления при успешном сохранении
- Confirmation dialogs для delete-операций

### Шаг 8: Undo функциональность
- Перед каждым изменением сохранять `manifest_store.backup = copy.deepcopy(manifest_store.current)`
- Кнопка "Revert" в navbar → `manifest_store.revert()`

---

## 🎨 UI/UX ТРЕБОВАНИЯ

- **Dark theme** (уже настроен через `data-bs-theme="dark"`)
- **Responsive** — работать на мобильных
- **Модальные окна** для сложных форм (не inline)
- **Inline-edit** для простых полей (двойной клик → input → Enter)
- **Drag & drop** (опционально) для переупорядочивания rooms/devices
- **Keyboard shortcuts**: Ctrl+S для сохранения, Esc для закрытия модалок

---

## 📌 ПРИМЕРЫ РЕФЕРЕНСОВ

### Пример endpoint для обновления комнаты:
```python
@app.post("/rooms/{room_id}/update")
async def update_room(
    request: Request,
    room_id: str,
    name: str = Form(...),
    sensors: str = Form(""),  # JSON string
):
    try:
        # Найти комнату в manifest_store.current
        room = next((r for r in manifest_store.current.rooms if r.id == room_id), None)
        if not room:
            raise HTTPException(404)

        # Обновить поля
        room.name = name
        room.sensors = json.loads(sensors) if sensors else {}

        # Вернуть обновлённый partial
        return templates.TemplateResponse(request, "partials/room_card.html", {"room": room})
    except Exception as e:
        return templates.TemplateResponse(
            request, "partials/save_error.html", {"error": str(e)}, status_code=400
        )
```

### Пример HTMX swap:
```html
<!-- Кнопка удаления -->
<button hx-delete="/rooms/{{ room.id }}"
        hx-target="#room-{{ room.id }}"
        hx-swap="outerHTML swap:300ms"
        hx-confirm="Удалить комнату {{ room.name }}?">
    Удалить
</button>
```

---

## ✅ КРИТЕРИИ ГОТОВНОСТИ

После реализации должно работать:

- [ ] Можно добавить новую комнату через UI
- [ ] Можно отредактировать имя комнаты
- [ ] Можно удалить комнату с подтверждением
- [ ] Можно добавить устройство в комнату
- [ ] Можно отредактировать тип и ID устройства
- [ ] Можно добавить behavior к устройству с выбором template
- [ ] Можно редактировать параметры behavior (brightness, schedule и т.д.)
- [ ] Все изменения валидируются Pydantic
- [ ] Кнопка "Save Manifest" сохраняет всё в YAML
- [ ] Кнопка "Revert" откатывает несохранённые изменения
- [ ] Есть индикатор несохранённых изменений
- [ ] Ошибки валидации показываются пользователю
- [ ] Всё работает без перезагрузки страницы (HTMX)
- [ ] Код покрыт тестами (минимум для endpoints)

---

## 🚀 НАЧАТЬ С

1. Прочитать `src/webui/models.py` и `src/webui/app.py`
2. Проанализировать текущий `src/webui/templates/index.html`
3. Создать `ManifestStore` класс в `app.py`
4. Реализовать **один CRUD цикл** (например, для rooms) как proof-of-concept
5. Показать результат и получить фидбек перед продолжением

---

## 💡 ВАЖНО

- **НЕ использовать JavaScript** кроме того что даёт HTMX/Bootstrap
- **НЕ ломать существующий функционал** — отображение должно работать как раньше
- **Сохранять читаемость YAML** после сохранения (без `default_flow_style=True`)
- **Комментировать** сложные места на русском языке

---

Используй этот промпт в Qwen Coder. Он содержит весь контекст, технические детали и критерии успеха. После реализации proof-of-concept (один CRUD цикл) — пришли мне результат, и я помогу доделать остальное! 🚀
