# 📋 Промпт для Qwen Coder: Расширенный WebUI с real-time визуализацией

Скопируй и используй этот промпт для работы с Qwen Coder:

---

## 🎯 РОЛЬ И КОНТЕКСТ

Ты — senior Python/Full-stack разработчик, работающий над проектом **Smart Home Platform V3**. Платформа управляет умным домом через FSM (конечные автоматы) и интегрируется с Home Assistant через WebSocket.

**Текущее состояние проекта:**

### ✅ Уже работает:
- **FastAPI приложение** в `src/webui/app.py` с WebUI на Bootstrap 5 dark theme
- **Pydantic модели** в `src/webui/models.py` (InstanceConfig, RoomConfig, DeviceConfig, BehaviorConfig, AutomationRules)
- **Jinja2 шаблоны** в `src/webui/templates/` — манифест отображается корректно
- **HTMX** уже используется для базовых интеракций
- **FSM Engine** (`src/core/fsm/engine.py`) — 8 конечных автоматов в работе
- **EventBus** (`src/core/events/event_bus.py`) — публикация/подписка на события
- **HAAdapter** (`src/adapters/ha_adapter.py`) — WebSocket к реальному Home Assistant на `ws://192.168.2.10:8123/api/websocket`
- **CommandDispatcher** с middleware цепочкой (ManualLockoutMiddleware уже есть)
- **ControlTracker** (`src/core/control_tracker.py`) — отслеживание ручных вмешательств
- **FSM Visualizer** (`src/core/fsm/visualizer.py`) — уже умеет генерировать Mermaid/Graphviz из манифеста!
- **CommandDispatcher** с приоритетной системой команд
- **Docker контейнер** на порту 8125

### 📁 Ключевые файлы для понимания:
```
src/core/
├── fsm/
│   ├── engine.py         # FSMEngine с методами get_state(), trigger()
│   ├── factory.py        # FSMFactory создаёт автоматы из манифеста
│   ├── visualizer.py     # ГЕНЕРИРУЕТ Mermaid из YAML/FSMDefinition
│   └── persistence.py    # StatePersistence для сохранения состояний
├── events/
│   └── event_bus.py      # publish(), subscribe() с trace_id
├── commands/
│   ├── dispatcher.py     # CommandDispatcher с приоритетами
│   └── middleware.py     # ManualLockoutMiddleware
├── control_tracker.py    # История ручных вмешательств
└── models/manifest.py    # Pydantic модели для манифеста

src/webui/
├── app.py, routes.py     # FastAPI endpoints
├── models.py             # Pydantic модели для WebUI
└── templates/            # Jinja2 шаблоны
```

### 🎯 Что уже генерируется в логах (будет полезно для истории):
```
HAAdapter: state_change received for binary_sensor.terassa_motion: 'off' -> 'on'
FSM Engine: Entity light.kitchen_lighting_10: Transition 'OFF' -> 'ON_MOTION'
CommandDispatcher: executing CommandIntent(device='light.kitchen', service='turn_on')
```

---

## 🎯 ЗАДАЧА

Реализовать **5 крупных фич** для расширенного WebUI:

### Фича 1: 🎨 **Визуализация FSM в реальном времени**
- Отображение активного состояния каждого FSM на карточке устройства
- Генерация Mermaid-диаграмм через существующий `FSMVisualizer`
- Подсветка текущего состояния на диаграмме (зелёный highlight)
- История последних 10 переходов состояния для каждого FSM

### Фича 2: 📈 **Графики событий и активности**
- Time-series график всех событий сенсоров за последние 24 часа
- Heatmap активности по часам суток (когда что срабатывает)
- График ручных вмешательств (manual overrides) vs автоматических действий
- Фильтрация по комнате/устройству/типу события

### Фича 3: 🎛️ **Manual Override интерфейс**
- Кнопка "Override" для каждого устройства — блокирует автоматизацию на N минут
- Панель активных overrides с таймерами обратного отсчёта
- История всех overrides с причинами
- Возможность продлить или досрочно снять override
- Интеграция с существующим `ManualLockoutMiddleware`

### Фича 4: 🤖 **AI Suggestions Panel**
- Отдельная вкладка/секция с предложениями от ИИ
- Карточки предложений: "Обнаружен паттерн...", "Рекомендую изменить...", "Конфликт правил..."
- Кнопки "Apply" / "Dismiss" / "Snooze" на каждом предложении
- Мок-данные на первом этапе (реальный ИИ будет позже)
- История применённых/отклонённых предложений

### Фича 5: ⚡ **WebSockets для live-обновлений**
- Real-time обновление состояний FSM без перезагрузки страницы
- Push-уведомления о важных событиях (manual override, ошибки, срабатывания)
- Live-лента событий в боковой панели
- Индикатор "online/offline" статуса соединения с HA

---

## 🔧 ТЕХНИЧЕСКИЕ ТРЕБОВАНИЯ

### Стек
- **Backend:** FastAPI + WebSockets + SQLite (для истории)
- **Frontend:** HTMX (где возможно) + vanilla JS (для WebSockets) + Chart.js/Plotly (графики)
- **Real-time:** FastAPI WebSockets (`@app.websocket()`)
- **Storage:** SQLite в `data/history.db` с таблицами events, fsm_transitions, manual_overrides, ai_suggestions

### Архитектурные принципы
- **НЕ ломать существующий функционал** — отображение манифеста должно работать как раньше
- **Использовать существующие компоненты** — `FSMVisualizer`, `ControlTracker`, `EventBus`
- **Event-driven** — подписываться на события через EventBus, а не поллить состояние
- **Graceful degradation** — если WebSocket отвалился, UI должен работать с HTMX fallback

### API Endpoints (добавить)

```python
# FSM визуализация
GET / api / fsm  # Список всех FSM с текущими состояниями
GET / api / fsm / {entity_id} / state  # Детальное состояние одного FSM
GET / api / fsm / {entity_id} / diagram  # Mermaid-диаграмма (HTML fragment)
GET / api / fsm / {entity_id} / history  # Последние 10 переходов

# История и графики
GET / api / history / events  # Все события (с фильтрами)
GET / api / history / activity - heatmap  # Heatmap данных для графика
GET / api / history / overrides  # История manual overrides

# Manual Override
POST / api / override / {entity_id}  # Создать override (body: {minutes, reason})
DELETE / api / override / {entity_id}  # Снять override
GET / api / override / active  # Список активных overrides

# AI Suggestions
GET / api / ai / suggestions  # Текущие предложения
POST / api / ai / suggestions / {id} / apply  # Применить предложение
POST / api / ai / suggestions / {id} / dismiss  # Отклонить
POST / api / ai / suggestions / {id} / snooze  # Отложить

# WebSocket
WS / ws / live  # Live обновления
```

### Структура данных для SQLite

```sql
-- История событий сенсоров
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    entity_id TEXT,
    old_state TEXT,
    new_state TEXT,
    event_type TEXT,
    trace_id TEXT
);

-- История переходов FSM
CREATE TABLE fsm_transitions (
    id INTEGER PRIMARY KEY,
    timestamp REAL,
    entity_id TEXT,
    from_state TEXT,
    to_state TEXT,
    trigger_name TEXT,
    trace_id TEXT
);

-- Manual overrides
CREATE TABLE manual_overrides (
    id INTEGER PRIMARY KEY,
    entity_id TEXT UNIQUE,
    started_at REAL,
    expires_at REAL,
    reason TEXT,
    user_id TEXT
);

-- AI suggestions
CREATE TABLE ai_suggestions (
    id INTEGER PRIMARY KEY,
    created_at REAL,
    suggestion_type TEXT,  -- 'pattern', 'conflict', 'optimization'
    title TEXT,
    description TEXT,
    affected_entities TEXT,  -- JSON array
    proposed_changes TEXT,   -- JSON
    status TEXT,  -- 'pending', 'applied', 'dismissed', 'snoozed'
    applied_at REAL,
    dismissed_at REAL
);

-- Индексы для быстрых запросов
CREATE INDEX idx_events_timestamp ON events(timestamp);
CREATE INDEX idx_events_entity ON events(entity_id);
CREATE INDEX idx_transitions_entity ON fsm_transitions(entity_id);
```

---

## 📝 ПОШАГОВЫЙ ПЛАН РЕАЛИЗАЦИИ

### ✅ Фича 1: Визуализация FSM — ГОТОВО
- ✅ Шаг 1.1: EventStore для истории событий
- ✅ Шаг 1.2: Интеграция с FSMVisualizer (endpoint /api/fsm/{entity_id}/diagram)
- ✅ Шаг 1.3: UI карточка устройства с FSM статусом
- ✅ Шаг 1.4: Modal с Mermaid-диаграммой

### ✅ Фича 2: Графики событий — ГОТОВО
- ✅ Шаг 2.1: API для графиков (/api/events/history)
- ✅ Шаг 2.2: Dashboard страница (/dashboard)
- ✅ Шаг 2.3: Chart.js интеграция для time-series графиков
- ⏳ Шаг 2.4: Heatmap (placeholder готов, требует реализации)

### ⏳ Фича 3: Manual Override

#### Шаг 1.1: История переходов FSM
- Создать `src/core/persistence/event_store.py` с SQLite backend
- Подписаться на события FSM через EventBus (event_type='fsm_transition')
- Сохранять каждый переход в таблицу `fsm_transitions`
- Добавить метод `get_recent_transitions(entity_id, limit=10)`

#### Шаг 1.2: Интеграция с FSMVisualizer
- Изучить существующий `src/core/fsm/visualizer.py`
- Создать endpoint `/api/fsm/{entity_id}/diagram` который возвращает Mermaid HTML
- Подсветить текущее состояние через CSS class `.current-state { fill: #0d6efd !important; }`
- Добавить метод `generate_with_highlight(entity_id, current_state)` в visualizer

#### Шаг 1.3: UI карточка устройства с FSM
- Обновить `templates/partials/device_card.html` (создать если нет)
- Добавить блок с FSM статусом:
  ```html
  <div class="fsm-status mt-2">
      <span class="badge bg-success">State: ON_MOTION</span>
      <small class="text-muted">Last: 2 min ago</small>
      <button hx-get="/api/fsm/{{ device.id }}/diagram"
              hx-target="#diagram-modal"
              class="btn btn-sm btn-outline-info ms-2">
          📊 View Diagram
      </button>
  </div>
  ```

#### Шаг 1.4: Modal с Mermaid-диаграммой
- Создать `templates/partials/fsm_diagram_modal.html`
- Включить Mermaid.js CDN в base layout
- Рендерить диаграмму клиент-side через `mermaid.init()`

### 📈 Фича 2: Графики событий

#### Шаг 2.1: Сбор истории
- Подписаться на все `state_change` события в HAAdapter
- Сохранять в `events` таблицу (batch insert каждые 5 сек для производительности)
- Добавить cleanup cron (удалять данные старше 30 дней)

#### Шаг 2.2: API для графиков
- `/api/history/events?from=&to=&entity_id=` — возвращает JSON для Chart.js
- `/api/history/activity-heatmap` — агрегированные данные по часам

#### Шаг 2.3: Dashboard страница
- Создать `templates/dashboard.html` (новая вкладка в навбаре)
- Интегрировать Chart.js для time-series
- Добавить date-range picker
- Фильтры по комнатам/устройствам

#### Шаг 2.4: Heatmap
- Использовать Cal-HeatMap или Plotly для визуализации активности по часам
- Показывать пики срабатываний автоматизации

### 🎛️ Фича 3: Manual Override

#### Шаг 3.1: Интеграция с ControlTracker
- Изучить `src/core/control_tracker.py`
- Создать wrapper `OverrideManager` который использует ControlTracker + SQLite
- При создании override:
  1. Сохранить в БД
  2. Вызвать `ManualLockoutMiddleware.record_manual_control(entity_id)`
  3. Опубликовать событие в EventBus для real-time обновления

#### Шаг 3.2: UI компонента Override
- Создать `templates/partials/override_panel.html`
- Для каждого устройства: кнопка "🔒 Override" → modal с выбором длительности
- Активные overrides показываются в виде badges с countdown
- Использовать JS `setInterval` для обновления таймеров (каждую секунду)

#### Шаг 3.3: Real-time updates
- Когда override создаётся/снимается, пушить всем WebSocket-клиентам
- UI обновляется мгновенно

### 🤖 Фича 4: AI Suggestions

#### Шаг 4.1: Mock генератор предложений
- Создать `src/core/ai/mock_suggestion_engine.py`
- Генерировать предложения на основе простых эвристик:
  - "Устройство X срабатывает > 50 раз в день — возможно стоит увеличить timeout"
  - "Конфликт: lighting и night_light одновременно активны на устройстве Y"
  - "Паттерн: свет в кухне включается в 23:15 ежедневно — добавить schedule?"
- Запускать анализ каждые 10 минут (background task)

#### Шаг 4.2: UI панель предложений
- Отдельная вкладка "🤖 AI Suggestions" в навбаре
- Карточки с цветовой индикацией типа (warning/info/success)
- Кнопки Apply/Dismiss/Snooze с подтверждением
- История решений в нижней части панели

#### Шаг 4.3: Применение предложений
- "Apply" — вносит изменения в `manifest_store` (из предыдущего промпта) и показывает diff
- "Dismiss" — помечает как `dismissed`
- "Snooze" — скрывает на N часов

### ⚡ Фича 5: WebSockets

#### Шаг 5.1: WebSocket endpoint
```python
@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()

    # Подписаться на EventBus
    async def on_event(event):
        await websocket.send_json(event)

    subscription_id = event_bus.subscribe("*", on_event)

    try:
        while True:
            # Держим соединение живым
            await websocket.receive_text()
    except WebSocketDisconnect:
        event_bus.unsubscribe(subscription_id)
```

#### Шаг 5.2: Client-side WebSocket handler
- Создать `src/webui/static/js/live.js`
- Подключать в base template
- Обрабатывать типы событий:
  - `fsm_transition` → обновить карточку устройства
  - `state_change` → обновить счётчики
  - `manual_override` → показать toast notification
  - `command_executed` → обновить статистику

#### Шаг 5.3: Auto-reconnect
- При разрыве соединения — попытка reconnect каждые 5 сек
- Индикатор статуса в navbar (🟢 connected / 🔴 disconnected)
- Fallback на HTMX polling когда WebSocket недоступен

---

## 🎨 UI/UX ТРЕБОВАНИЯ

### Навигация
Расширить navbar:
```html
<nav>
    <a href="/">🏠 Manifest</a>
    <a href="/dashboard">📊 Dashboard</a>
    <a href="/devices">🔌 Devices & FSM</a>
    <a href="/overrides">🎛️ Overrides</a>
    <a href="/ai">🤖 AI Suggestions</a>
</nav>
```

### Dark theme консистентность
- Все новые компоненты в dark theme
- Цветовая палитра:
  - Success: `#0d6efd` (Bootstrap primary)
  - Warning: `#ffc107`
  - Danger: `#dc3545`
  - Info: `#0dcaf0`
  - Active state: `#198754` с glow-эффектом

### Animations
- Плавное появление новых событий в ленте (`fade-in`)
- Pulse эффект на активных FSM (`animation: pulse 2s infinite`)
- Smooth transitions между состояниями
- Toast notifications со slide-in animation

### Responsive
- Dashboard адаптируется под мобильные (stack columns)
- Графики уменьшаются/скрываются на малых экранах
- Touch-friendly кнопки (min 44px)

---

## 🔌 ПРИМЕРЫ РЕАЛИЗАЦИИ

### Пример: WebSocket client handler

```javascript
// static/js/live.js
class LiveUpdater {
    constructor() {
        this.ws = null;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/live`);

        this.ws.onopen = () => {
            console.log('✅ WebSocket connected');
            this.updateStatusIndicator('connected');
            this.reconnectDelay = 1000;  // Reset
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleEvent(data);
        };

        this.ws.onclose = () => {
            console.log('❌ WebSocket disconnected');
            this.updateStatusIndicator('disconnected');
            setTimeout(() => this.connect(), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
        };
    }

    handleEvent(data) {
        switch (data.type) {
            case 'fsm_transition':
                this.updateFsmCard(data.entity_id, data.to_state);
                break;
            case 'manual_override':
                this.showOverrideToast(data);
                break;
            case 'state_change':
                this.updateSensorValue(data.entity_id, data.new_state);
                break;
        }
    }

    updateFsmCard(entityId, newState) {
        const card = document.querySelector(`[data-fsm-entity="${entityId}"]`);
        if (card) {
            const badge = card.querySelector('.fsm-state-badge');
            badge.textContent = newState;
            badge.classList.add('pulse-animation');
            setTimeout(() => badge.classList.remove('pulse-animation'), 2000);
        }
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.liveUpdater = new LiveUpdater();
});
```

### Пример: Mermaid с подсветкой состояния

```python
# src/webui/routes/fsm.py
@app.get("/api/fsm/{entity_id}/diagram")
async def get_fsm_diagram(request: Request, entity_id: str):
    fsm_def = fsm_engine.get_definition(entity_id)
    current_state = fsm_engine.get_state(entity_id)

    # Генерируем Mermaid с подсветкой
    mermaid_code = f"""
stateDiagram-v2
    [*] --> {fsm_def.initial_state}
"""
    for transition in fsm_def.transitions:
        mermaid_code += (
            f"    {transition.from_state} --> {transition.to_state}: {transition.trigger}\n"
        )

    # Добавляем class для текущего состояния
    mermaid_code += f"\n    class {current_state} currentState\n"
    mermaid_code += "    classDef currentState fill:#0d6efd,stroke:#fff,stroke-width:3px\n"

    return templates.TemplateResponse(
        request, "partials/fsm_diagram.html", {"mermaid_code": mermaid_code, "entity_id": entity_id}
    )
```

---

## ✅ КРИТЕРИИ ГОТОВНОСТИ

После реализации должно работать:

### Фича 1: FSM визуализация
- [ ] На карточке каждого устройства видно текущее состояние FSM
- [ ] Кнопка "📊 View Diagram" открывает модальное окно с Mermaid-диаграммой
- [ ] Текущее состояние подсвечено на диаграмме
- [ ] Есть история последних 10 переходов
- [ ] При изменении состояния карточка обновляется через WebSocket

### Фича 2: Графики
- [ ] Dashboard страница с time-series графиком событий за 24 часа
- [ ] Heatmap активности по часам
- [ ] Фильтры по комнатам/устройствам работают
- [ ] Данные сохраняются в SQLite
- [ ] Старые данные автоматически удаляются (30 дней)

### Фича 3: Manual Override
- [ ] Кнопка Override на каждом устройстве работает
- [ ] Активные overrides видны с countdown таймерами
- [ ] Override интегрирован с ManualLockoutMiddleware (автоматизация реально блокируется)
- [ ] История overrides сохраняется
- [ ] Через WebSocket все клиенты видят новые overrides

### Фича 4: AI Suggestions
- [ ] Панель предложений с мок-данными
- [ ] Кнопки Apply/Dismiss/Snooze работают
- [ ] Применённые предложения реально меняют манифест (связь с предыдущим промптом)
- [ ] История решений сохраняется

### Фича 5: WebSockets
- [ ] Состояния FSM обновляются в реальном времени без перезагрузки
- [ ] Индикатор статуса соединения в navbar
- [ ] Auto-reconnect при разрыве
- [ ] Fallback на HTMX когда WebSocket недоступен
- [ ] Toast-уведомления о важных событиях

### Общие
- [ ] Всё работает в dark theme
- [ ] Responsive design
- [ ] Тесты для новых endpoints
- [ ] Документация API
- [ ] Нет регрессий существующего функционала

---

## 🚀 ПОРЯДОК РЕАЛИЗАЦИИ (рекомендуемый)

1. **Сначала Фича 5 (WebSockets)** — это фундамент для всех real-time обновлений
2. **Затем Фича 1 (FSM визуализация)** — использует WebSocket и даёт немедленную ценность
3. **Потом Фича 3 (Manual Override)** — критично для production использования
4. **Далее Фича 2 (Графики)** — нужна история, которая собирается автоматически
5. **В конце Фича 4 (AI Suggestions)** — каркас под будущий реальный ИИ

После каждой фичи делай **демо-видео или скриншоты** и показывай результат перед переходом к следующей.

---

## 💡 ВАЖНО

- **Используй существующие компоненты** — не пиши свой FSM engine, используй FSMEngine
- **Не дублируй логику** — ControlTracker уже делает часть работы для overrides
- **FSMVisualizer уже существует** — расширь его, а не пиши с нуля
- **SQLite для начала** — потом можно мигрировать на PostgreSQL/InfluxDB
- **WebSockets + HTMX fallback** — для надёжности
- **Моки вместо реального ИИ** — реальная интеграция будет в отдельном промпте
- **Пиши тесты** для каждого endpoint (pytest + httpx)

---

## 📚 ДОПОЛНИТЕЛЬНЫЕ РЕСУРСЫ

- **FastAPI WebSockets:** https://fastapi.tiangolo.com/advanced/websockets/
- **Chart.js:** https://www.chartjs.org/docs/latest/
- **Mermaid State Diagrams:** https://mermaid.js.org/syntax/stateDiagram.html
- **HTMX WebSockets:** https://htmx.org/extensions/web-sockets/ (альтернатива vanilla JS)

---

Используй этот промпт в Qwen Coder. Начни с **Фичи 5 (WebSockets)** как фундамента, потом переходи по порядку. После каждой фичи показывай мне результат — я помогу с интеграцией и отладкой! 🚀
