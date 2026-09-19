# Phase 9.75: Production Deployment Preparation

## Overview
Критическая фаза подготовки платформы к развёртыванию на реальном Home Assistant без риска нарушения работы существующих автоматизаций.

## User Stories

### 1. Safe Deployment Strategy (CRITICAL)
**Как** администратор умного дома,
**Я хочу** развернуть платформу в "теневом режиме" параллельно с существующими автоматизациями,
**Чтобы** протестировать работу платформы без риска сломать текущие сценарии.

#### Acceptance Criteria
- [ ] Платформа может работать в shadow mode (только логирование, без вызова сервисов HA)
- [ ] Возможность переключения между shadow/active режимами через конфиг
- [ ] Graceful fallback при ошибках платформы (автоматизации HA продолжают работать)
- [ ] Docker Compose конфигурация для production с health checks
- [ ] Скрипт безопасного развёртывания с rollback
- [ ] Документация по deployment в `docs/deployment/README.md`

#### Implementation Plan
1. Добавить режим `shadow_mode` в HAAdapter
2. Создать `docker-compose.prod.yml` с proper health checks
3. Написать `scripts/safe-deploy.sh` с проверками и rollback
4. Создать comprehensive deployment guide

---

### 2. Enhanced Logging Integration (HIGH)
**Как** разработчик и администратор,
**Я хочу** видеть логи платформы в интерфейсе Home Assistant и веб-интерфейсе,
**Чтобы** оперативно диагностировать проблемы и мониторить работу автоматизаций.

#### Acceptance Criteria
- [ ] Интеграция с системой логирования HA Supervisor
- [ ] Веб-интерфейс для просмотра логов в реальном времени (`/logs`)
- [ ] Фильтрация логов по уровню (DEBUG, INFO, WARNING, ERROR)
- [ ] Фильтрация по модулям (FSM, Event, Command, etc.)
- [ ] Поиск по тексту в логах
- [ ] Экспорт логов в файл
- [ ] Ротация логов с сохранением истории (7 дней)
- [ ] Persistence логов на диск

#### Implementation Plan
1. Создать `services/logging_service.py` с интеграцией HA logging
2. Добавить routes в WebUI: `webui/routes/logs.py`
3. Создать template `webui/templates/logs.html` с HTMX для real-time updates
4. Настроить log rotation через `logging.handlers.RotatingFileHandler`

---

### 3. Automatic Manifest Generator (HIGH)
**Как** пользователь,
**Я хочу** автоматически сгенерировать манифест на основе реальных устройств в HA,
**Чтобы** не создавать конфигурацию вручную для десятков устройств.

#### Acceptance Criteria
- [ ] CLI команда `smart-home generate-manifest --url <URL> --token <TOKEN>`
- [ ] Подключение к HA API и получение всех entities
- [ ] Авто-классификация устройств по типам (light, climate, fan, etc.)
- [ ] Группировка по areas/rooms из HA
- [ ] Генерация базовых behaviors для каждого типа устройства
- [ ] Интерактивный режим просмотра и редактирования перед сохранением
- [ ] Сохранение в `instances/<name>/manifest.yaml`
- [ ] Web UI интерфейс для генерации (опционально)

#### Implementation Plan
1. Создать `cli/commands/generate_manifest.py`
2. Расширить `core/manifest_generator.py` для работы с HA API
3. Добавить маппинг entity domains → device types → behavior templates
4. Реализовать interactive CLI review с использованием `rich` или `questionary`

---

### 4. Dashboard Generator for Platform Management (MEDIUM)
**Как** пользователь,
**Я хочу** иметь готовый Lovelace dashboard для мониторинга платформы,
**Чтобы** видеть состояние FSM, активные behaviors и ручные overrides в реальном времени.

#### Acceptance Criteria
- [ ] CLI команда `smart-home generate-dashboard --output lovelace_platform.yaml`
- [ ] Карточки для мониторинга:
  * Состояния FSM для каждого устройства
  * Активные behaviors с приоритетами
  * Ручные overrides (manual lockout status)
  * Ошибки и предупреждения платформы
  * Метрики производительности (команд в секунду, latency)
- [ ] Контролы для управления:
  * Reload конфигурации
  * Toggle debug mode
  * Просмотр логов
  * Health check платформы
- [ ] Auto-refresh карточек (real-time updates)
- [ ] Импорт в HA через UI или автоматически

#### Implementation Plan
1. Создать `dashboard/platform_dashboard.py`
2. Расширить `lovelace_generator.py` для поддержки platform cards
3. Добавить CLI команду `generate-dashboard`
4. Создать шаблоны карточек для различных метрик

---

## Technical Requirements

### Security
- Все токены HA должны храниться через Secrets Management (`core/secrets.py`)
- HTTPS для всех внешних соединений
- Валидация SSL сертификатов

### Performance
- Генерация манифеста: < 30 секунд для 100+ устройств
- Генерация dashboard: < 5 секунд
- Log viewing: < 100ms latency для real-time updates

### Compatibility
- Поддержка HA 2024.1+
- Python 3.10, 3.11, 3.12
- Backward compatibility с existing manifests

---

## Testing Strategy

### Unit Tests
- Тесты для manifest generator с mock HA API
- Тесты для dashboard generator
- Тесты для logging service

### Integration Tests
- Тесты с реальным HA instance (test environment)
- E2E тесты deployment pipeline

### Manual Testing
- Развёртывание на test HA instance
- Проверка всех user stories

---

## Definition of Done
- [ ] Все 4 user story реализованы
- [ ] Тесты написаны и проходят (покрытие >80%)
- [ ] Документация обновлена
- [ ] CI/CD pipeline зелёный
- [ ] Pre-commit hooks проходят
- [ ] Проведено ручное тестирование на test HA instance

---

## Dependencies
- Phase 9: Observability & Reliability ✅ (completed)
- Phase 10: Architecture Improvements ✅ (completed)
- Secrets Management (Phase 9.3) ✅ (completed)

---

## Files to Create/Modify

### New Files
- `docs/deployment/README.md`
- `docker-compose.prod.yml`
- `scripts/safe-deploy.sh`
- `services/logging_service.py`
- `webui/routes/logs.py`
- `webui/templates/logs.html`
- `cli/commands/generate_manifest.py`
- `dashboard/platform_dashboard.py`

### Modified Files
- `adapters/ha_adapter.py` (shadow mode)
- `core/manifest_generator.py` (HA API integration)
- `src/dashboard/lovelace_generator.py` (platform cards)
- `.ai/03_ROADMAP.md` (this file)
