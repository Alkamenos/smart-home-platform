# Dashboard Generator for Platform Management

**Приоритет:** MEDIUM
**Оценка:** 1 день
**Категория:** Production Deployment

## Цель

Автоматически генерировать Lovelace dashboard для Home Assistant, предоставляющий полную видимость состояния платформы: FSM states, активные behaviors, ошибки, метрики и элементы управления.

## Проблема

Пользователям сложно:
1. Мониторить состояние платформы без специализированного интерфейса
2. Видеть какие FSM в каких состояниях находятся
3. Понимать почему сработала или не сработала автоматизация
4. Быстро управлять платформой (reload, debug mode, health check)
5. Отслеживать метрики производительности

Существующий Web UI предоставляет базовую информацию, но нет интеграции с нативным интерфейсом HA.

## Предлагаемое решение

### 1. Lovelace Dashboard Generator

CLI команда для генерации YAML конфига dashboard:
```bash
smart-home generate-dashboard \
  --output lovelace_platform.yaml \
  --instance my_home
```

### 2. Карточки мониторинга

Dashboard включает карточки:

**FSM State Overview**
- Таблица всех FSM с текущими состояниями
- Цветовая индикация (зелёный = active, серый = idle, красный = error)
- Клик для детальной информации

**Active Behaviors**
- Список активных behaviors прямо сейчас
- Время активности
- Возможность принудительной остановки

**Manual Overrides**
- Устройства под ручным управлением
- Кто установил override (пользователь/автоматизация)
- Кнопка сброса override

**Errors & Warnings**
- Последние ошибки платформы
- Счётчик ошибок за 24 часа
- Ссылка на полные логи

**Platform Metrics**
- Графики: события/сек, команды/сек, latency
- Uptime платформы
- Статус подключения к HA

### 3. Элементы управления

**Control Panel**
- Кнопка "Reload Configuration"
- Переключатель "Debug Mode"
- Кнопка "Health Check"
- Кнопка "Export Logs"

**FSM Controls**
- Принудительный переход состояния (для отладки)
- Сброс FSM в начальное состояние
- Pause/Resume конкретную FSM

### 4. Auto-Update при изменениях

При изменении конфигурации платформы:
- Автоматическая перегенерация dashboard
- Или уведомление: "Доступна новая версия dashboard"

## План реализации

1. **Dashboard Generator Engine**
   - `core/dashboard_generator.py` — основная логика
   - Шаблоны карточек Lovelace
   - Интеграция с данными платформы

2. **CLI Command**
   - `cli/commands/generate_dashboard.py`
   - Флаги: --output, --instance, --preview
   - Валидация выходного YAML

3. **Lovelace Templates**
   - Шаблоны для каждого типа карточки
   - Адаптивный дизайн для mobile/desktop
   - Тёмная/светлая тема

4. **WebSocket Integration**
   - Real-time обновление карточек
   - Подписка на события платформы
   - Мгновенное отражение изменений состояния

5. **Documentation**
   - Инструкция по импорту dashboard в HA
   - Настройка автообновления
   - Кастомизация карточек

## Файлы

- `core/dashboard_generator.py` — движок генерации dashboard
- `core/templates/lovelace/` — шаблоны карточек
- `cli/commands/generate_dashboard.py` — CLI команда
- `webui/routes/dashboard.py` — API для dashboard данных
- `tests/test_dashboard_generator.py` — тесты генератора
- `docs/user-guide/dashboard.md` — документация по dashboard
- `examples/lovelace_platform.yaml` — пример сгенерированного dashboard

## Критерии успеха

- [ ] Генерация работает одной командой
- [ ] Dashboard импортируется в HA без ошибок
- [ ] Все карточки отображают актуальные данные
- [ ] Real-time обновления работают через WebSocket
- [ ] Элементы управления функционируют
- [ ] Мобильная версия адаптивна
- [ ] Покрытие тестами >85%

## User Stories

### US-1: Импорт готового dashboard
**Как** пользователь HA
**Хочу** импортировать готовый dashboard одной командой
**Чтобы** сразу видеть состояние платформы

**Acceptance Criteria:**
- Команда `smart-home generate-dashboard --output lovelace.yaml`
- Импорт через HA UI: Settings → Dashboards → Import
- Все карточки отображаются корректно
- Данные обновляются в реальном времени

### US-2: Мониторинг FSM состояний
**Как** администратор
**Хочу** видеть состояния всех FSM на одном экране
**Чтобы** быстро понимать что происходит в системе

**Acceptance Criteria:**
- Таблица со всеми FSM
- Цветовая индикация состояний
- Детали по клику на FSM
- Фильтрация по комнатам/типам

### US-3: Управление платформой
**Как** оператор
**Хочу** управлять платформой из dashboard
**Чтобы** не переключаться в другие интерфейсы

**Acceptance Criteria:**
- Кнопка Reload работает
- Debug Mode toggle переключается
- Health Check показывает статус
- Export Logs скачивает файл

### US-4: Отслеживание ошибок
**Как** разработчик
**Хочу** видеть ошибки в реальном времени
**Чтобы** быстро реагировать на проблемы

**Acceptance Criteria:**
- Карточка "Recent Errors" показывает последние 10 ошибок
- Красный индикатор при новых ошибках
- Клик открывает детали ошибки
- Ссылка на полный лог

## Структура Dashboard

```yaml
title: Smart Home Platform
views:
  - title: Overview
    cards:
      - type: custom:platform-health-card
      - type: custom:fsm-states-table
      - type: custom:active-behaviors-list
      - type: custom:metrics-graph

  - title: FSM Details
    cards:
      - type: custom:fsm-detail-card
        entity_id: light.hallway_fsm
      - type: custom:fsm-history-graph

  - title: Controls
    cards:
      - type: buttons
        entities:
          - script.reload_platform
          - switch.debug_mode
          - button.health_check
```

## Примеры карточек

### FSM States Table

```yaml
type: custom:auto-entities
card:
  type: table
  columns:
    - name: FSM
      field: name
    - name: State
      field: state
    - name: Room
      field: room
    - name: Last Change
      field: last_changed
filter:
  include:
    - domain: script
      state: "*"
sort:
  - field: room
```

### Platform Health Card

```yaml
type: custom:platform-health-card
entities:
  - entity: sensor.platform_uptime
  - entity: sensor.platform_status
  - entity: sensor.active_fsm_count
  - entity: sensor.error_count_24h
show_graph: true
refresh_interval: 5
```

### Metrics Graph

```yaml
type: history-graph
entities:
  - entity: sensor.events_per_second
  - entity: sensor.commands_per_second
  - entity: sensor.average_latency
hours_to_show: 24
refresh_interval: 10
```

## Конфигурация

```yaml
# configuration.yaml
dashboard_generator:
  output_path: lovelace_platform.yaml
  auto_import: false  # автоматически импортировать в HA
  refresh_interval: 5  # секунд
  theme: auto  # auto | light | dark
  views:
    - overview
    - fsm_details
    - controls
    - metrics
  cards:
    fsm_states:
      show_room: true
      show_last_changed: true
      color_by_state: true
    metrics:
      hours_to_show: 24
      update_interval: 10
```

## Риски

1. **Несовместимость версий HA** — изменения в Lovelace API
   **Mitigation:** Тестирование на минимальной поддерживаемой версии HA, документация требований

2. **Отсутствие custom cards** — пользователь не установил нужные карточки
   **Mitigation:** Использовать только стандартные карточки HA, optional custom cards

3. **Performance при большом числе FSM** — тормоза при 50+ FSM
   **Mitigation:** Пагинация, виртуализация списка, lazy loading

4. **Real-time updates нагрузка** — много WebSocket подключений
   **Mitigation:** Rate limiting, throttle обновлений, fallback на polling

## Метрики успеха

- Время генерации dashboard: < 3 секунд
- Количество карточек по умолчанию: 8-12
- Задержка real-time обновлений: < 2 секунд
- Поддерживаемое число FSM: до 100 без деградации
- Удовлетворённость пользователей: >4.5/5

## Интеграция с HACS

Для расширенных карточек推荐 установить через HACS:
- `custom:auto-entities`
- `custom:button-card`
- `custom:mini-graph-card`

Инструкция будет включена в документацию.
