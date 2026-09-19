# Enhanced Logging Integration

**Приоритет:** HIGH
**Оценка:** 1-2 дня
**Категория:** Production Deployment

## Цель

Предоставить пользователям удобные инструменты для мониторинга, анализа и отладки работы платформы через интеграцию с логированием Home Assistant и собственный web-интерфейс.

## Проблема

Текущее состояние:
- Логи выводятся только в stdout/файл
- Нет централизованного интерфейса для просмотра
- Сложно фильтровать по уровням, компонентам, временным меткам
- Нет интеграции с HA Supervisor panel
- Отсутствует ротация и долгосрочное хранение

## Предлагаемое решение

### 1. HA Logging Integration

Интеграция с системой логирования Home Assistant:
- Регистрация как HA logging provider
- Отображение логов в Supervisor → System → Logs
- Поддержка уровней: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Цветовая кодировка уровней

### 2. Web UI для просмотра логов

Специализированный интерфейс `/logs`:
- Real-time streaming через WebSocket
- Фильтры по:
  - Уровню (ERROR, WARNING, INFO, DEBUG)
  - Компоненту (core, services, adapters)
  - Временному диапазону
  - Ключевым словам
- Поиск по тексту с подсветкой совпадений
- Пагинация для больших объёмов
- Автопрокрутка в real-time режиме

### 3. Log Rotation & Persistence

- Автоматическая ротация каждые 24 часа или при достижении размера
- Хранение последних 7 дней
- Сжатие старых логов (gzip)
- Экспорт в форматах: JSON, CSV, TXT

### 4. Structured Logging

Переход на структурированные логи:
```json
{
  "timestamp": "2026-09-20T14:30:00Z",
  "level": "ERROR",
  "component": "core.fsm.engine",
  "message": "Transition failed",
  "context": {
    "fsm_id": "hallway_light",
    "from_state": "off",
    "to_state": "on",
    "trigger": "motion_detected",
    "error": "Guard check failed"
  }
}
```

## План реализации

1. **Logging Service**
   - Создать `services/logging_service.py`
   - Настроить handlers для файла, HA API, WebSocket
   - Реализовать ротацию и архивацию

2. **HA Integration**
   - Интеграция с HA logging API
   - Регистрация источника логов
   - Тестирование в Supervisor panel

3. **Web UI Routes**
   - `webui/routes/logs.py` — API endpoints
   - `webui/templates/logs.html` — frontend
   - WebSocket endpoint для real-time streaming

4. **Structured Logging Migration**
   - Обновить все `logger.info()` на структурированный формат
   - Добавить контекст в каждое сообщение
   - Создать helper функции для логирования

5. **Export Functionality**
   - CLI команда `smart-home export-logs`
   - Web UI кнопка экспорта
   - Поддержка форматов JSON/CSV/TXT

## Файлы

- `services/logging_service.py` — центральный сервис логирования
- `services/log_rotation.py` — управление ротацией и хранением
- `webui/routes/logs.py` — REST API для логов
- `webui/templates/logs.html` — шаблон страницы логов
- `webui/static/js/logs_viewer.js` — frontend лог viewer
- `core/structured_logger.py` — обёртка для структурированного логирования
- `cli/commands/export_logs.py` — CLI экспорт логов
- `tests/test_logging_service.py` — тесты сервиса логирования
- `tests/test_log_rotation.py` — тесты ротации
- `docs/logging/README.md` — документация по логированию

## Критерии успеха

- [ ] Логи отображаются в HA Supervisor panel
- [ ] Web UI `/logs` работает с real-time обновлением
- [ ] Фильтры и поиск функционируют корректно
- [ ] Ротация работает автоматически
- [ ] Экспорт в 3 форматах доступен
- [ ] Structured logging внедрён во всех компонентах
- [ ] Покрытие тестами >90%

## User Stories

### US-1: Просмотр логов в HA Supervisor
**Как** пользователь Home Assistant
**Хочу** видеть логи платформы в стандартной панели Supervisor
**Чтобы** не переключаться между интерфейсами

**Acceptance Criteria:**
- Логи появляются в Supervisor → System → Logs
- Можно выбрать источник "Smart Home FSM Platform"
- Отображаются уровни и временные метки
- Цветовая индикация ошибок

### US-2: Real-time мониторинг через Web UI
**Как** разработчик/администратор
**Хочу** видеть логи в реальном времени в браузере
**Чтобы** отслеживать работу платформы live

**Acceptance Criteria:**
- Страница доступна по `/logs`
- Новые записи появляются без перезагрузки (WebSocket)
- Есть кнопка Pause/Resume автопрокрутки
- Визуальное разделение уровней (цветом)

### US-3: Фильтрация и поиск
**Как** отладчик
**Хочу** фильтровать логи по уровню и искать текст
**Чтобы** быстро находить проблемы

**Acceptance Criteria:**
- Чекбоксы для выбора уровней (ERROR, WARNING, INFO, DEBUG)
- Текстовое поле поиска с мгновенной фильтрацией
- Подсветка найденных совпадений
- Счётчик найденных записей

### US-4: Экспорт логов для анализа
**Как** аналитик
**Хочу** выгрузить логи за период в формате JSON/CSV
**Чтобы** проанализировать в сторонних инструментах

**Acceptance Criteria:**
- Выбор временного диапазона (с/по)
- Выбор формата экспорта
- Скачивание файла через браузер
- CLI альтернатива: `smart-home export-logs --from=2026-09-01 --to=2026-09-20 --format=json`

## Архитектура

```
┌─────────────────┐
│  Application    │
│   Components    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ StructuredLogger│
└────────┬────────┘
         │
    ┌────┴────┬──────────┬─────────────┐
    ▼         ▼          ▼             ▼
┌────────┐ ┌────────┐ ┌─────────┐ ┌──────────┐
│ File   │ │ HA API │ │WebSocket│ │  Memory  │
│ Handler│ │Handler │ │ Handler │ │  Buffer  │
└────────┘ └────────┘ └─────────┘ └──────────┘
                                  │
                                  ▼
                          ┌─────────────┐
                          │ Log Rotation│
                          │   Service   │
                          └─────────────┘
```

## Конфигурация

```yaml
# configuration.yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: structured  # structured | simple
  outputs:
    - type: file
      path: /var/log/smart-home/platform.log
      rotation: daily
      retention_days: 7
    - type: home_assistant
      enabled: true
    - type: websocket
      enabled: true
      endpoint: /ws/logs
  filters:
    include_components:
      - core.*
      - services.*
    exclude_components:
      - tests.*
```

## Риски

1. **Performance Overhead** — структурированное логирование медленнее
   **Mitigation:** Асинхронная запись, буферизация, sampling для DEBUG уровня

2. **Storage Consumption** — логи занимают много места
   **Mitigation:** Автоматическая ротация, сжатие, лимит хранения

3. **Sensitive Data** — логи могут содержать токены/пароли
   **Mitigation:** Автоматическая маскировка секретов, валидация перед записью

4. **WebSocket Load** — много подключений для real-time
   **Mitigation:** Rate limiting, ограничение числа клиентов, fallback на polling

## Метрики успеха

- Время загрузки страницы логов: < 2 секунд
- Задержка real-time updates: < 500ms
- Поддержка одновременных подключений: до 10 клиентов
- Размер сжатых логов за день: < 50MB
- Полнота контекста в логах: 100% ошибок имеют context
