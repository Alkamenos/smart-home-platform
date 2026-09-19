# Safe Deployment Strategy for Home Assistant

**Приоритет:** CRITICAL
**Оценка:** 2-3 дня
**Категория:** Production Deployment

## Цель

Обеспечить безопасное развёртывание платформы на реальном Home Assistant без риска нарушения работы существующих автоматизаций умного дома.

## Проблема

Прямая замена существующих автоматизаций HA на новую платформу несёт высокие риски:
1. Ошибки в конфигурации могут оставить дом без автоматизации
2. Невозможность быстрого отката при проблемах
3. Отсутствие параллельного режима работы для тестирования
4. Нет информирования о том, какие действия платформа собирается выполнить

## Предлагаемое решение

### 1. Shadow Mode (Режим тени)

Платформа работает параллельно с существующими автоматизациями HA:
- Получает все события от HA
- Вычисляет предполагаемые действия
- **НЕ выполняет** действия реально
- Логирует: "Если бы я был активен, я бы сделал X"
- Web UI показывает разницу между текущими и планируемыми действиями

```yaml
# configuration.yaml
deployment:
  mode: shadow  # shadow | active | hybrid
  log_decisions: true
  dry_run: true
```

### 2. Graceful Fallback

При ошибках платформа автоматически:
- Передаёт управление обратно штатным автоматизациям HA
- Отправляет уведомление администратору
- Сохраняет состояние для последующей диагностики
- Предлагает команду восстановления: `smart-home rollback`

### 3. Docker Compose Production Configuration

Готовые конфиги для развёртывания:
- `docker-compose.prod.yml` — production стек
- Health checks для всех сервисов
- Auto-restart при падениях
- Persistent volumes для логов и состояния
- Network isolation

### 4. Deployment Script с Rollback

Скрипт `scripts/safe-deploy.sh`:
```bash
# Pre-deployment checks
./scripts/safe-deploy.sh --check

# Create backup
./scripts/safe-deploy.sh --backup

# Deploy in shadow mode
./scripts/safe-deploy.sh --deploy --mode=shadow

# Monitor for 24 hours
./scripts/safe-deploy.sh --monitor --duration=24h

# Switch to active mode if all good
./scripts/safe-deploy.sh --activate

# Rollback if needed
./scripts/safe-deploy.sh --rollback
```

## План реализации

1. **Shadow Mode Implementation**
   - Добавить флаг `dry_run` в `CommandDispatcher`
   - Модифицировать `HAAdapter` для режима "только логирование"
   - Создать `DeploymentManager` для управления режимами

2. **Backup & Rollback System**
   - Скрипт бэкапа текущих автоматизаций HA
   - Экспорт в YAML через HA API
   - Механизм восстановления из бэкапа

3. **Docker Production Configs**
   - `docker-compose.prod.yml` с production настройками
   - `.env.production` шаблон
   - Dockerfile с оптимизациями

4. **Deployment Scripts**
   - `scripts/safe-deploy.sh` — основной скрипт
   - `scripts/backup-ha-automations.py` — бэкап автоматизаций
   - `scripts/restore-ha-automations.py` — восстановление

5. **Documentation**
   - `docs/deployment/README.md` — полное руководство
   - `docs/deployment/SHADOW_MODE.md` — как использовать shadow mode
   - `docs/deployment/ROLLBACK.md` — инструкция по откату

## Файлы

- `core/deployment_manager.py` — управление режимами развёртывания
- `services/backup_service.py` — сервис бэкапа/восстановления
- `docker-compose.prod.yml` — production docker compose
- `scripts/safe-deploy.sh` — скрипт безопасного развёртывания
- `scripts/backup-ha-automations.py` — бэкап автоматизаций HA
- `scripts/restore-ha-automations.py` — восстановление автоматизаций
- `docs/deployment/README.md` — основная документация
- `docs/deployment/SHADOW_MODE.md` — shadow mode guide
- `docs/deployment/ROLLBACK.md` — rollback procedures
- `tests/test_deployment.py` — тесты deployment сценариев
- `tests/test_backup_service.py` — тесты бэкапа

## Критерии успеха

- [ ] Shadow mode полностью функционален
- [ ] Бэкап автоматизаций HA работает через API
- [ ] Rollback восстанавливает состояние за < 5 минут
- [ ] Docker Compose поднимает все сервисы
- [ ] Документация покрывает все сценарии
- [ ] Тесты покрывают >85% кода
- [ ] E2E тест развёртывания на test instance

## User Stories

### US-1: Развернуть код на реальном устройстве
**Как** администратор умного дома
**Хочу** безопасно развернуть платформу на production HA
**Чтобы** протестировать её без риска сломать существующие автоматизации

**Acceptance Criteria:**
- Запуск через `docker-compose -f docker-compose.prod.yml up -d`
- Все сервисы стартуют и проходят health checks
- Платформа подключается к HA через предоставленный токен
- Логи доступны через `docker-compose logs -f`

### US-2: Параллельный режим работы
**Как** осторожный пользователь
**Хочу** запустить платформу в shadow mode
**Чтобы** видеть что она сделала бы, не выполняя действия реально

**Acceptance Criteria:**
- Команда `smart-home set-mode --mode=shadow`
- В логах видно: "[DRY RUN] Would execute: light.turn_on(entity_id=light.kitchen)"
- Web UI показывает колонку "Planned Actions" vs "Actual Actions"
- Существующие автоматизации HA продолжают работать

### US-3: Быстрый откат
**Как** администратор
**Хочу** сделать rollback одной командой
**Чтобы** восстановить работу умного дома при критических ошибках

**Acceptance Criteria:**
- Команда `smart-home rollback --to-backup=<timestamp>`
- Автоматизации HA восстанавливаются из бэкапа
- Платформа останавливается gracefully
- Уведомление об успешном откате отправляется в Telegram/Email

## Риски

1. **API Rate Limiting** — HA API может ограничивать частоту запросов
   **Mitigation:** Добавить rate limiting в HAAdapter, кэширование состояний

2. **Incomplete Backup** — не все автоматизации будут захвачены
   **Mitigation:** Явный список типов автоматизаций для бэкапа, валидация полноты

3. **State Inconsistency** — рассинхронизация состояний при rollback
   **Mitigation:** Snapshot состояний перед развёртыванием, проверка консистентности

4. **User Error** — неправильная конфигурация приведёт к проблемам
   **Mitigation:** Интерактивный wizard конфигурации, валидация перед применением

## Интеграция с Home Assistant

### Вариант A: Home Assistant Add-on (рекомендуется)
```json
{
  "name": "Smart Home FSM Platform",
  "version": "1.0.0",
  "slug": "smart_home_fsm",
  "description": "Advanced FSM-based home automation platform",
  "arch": ["armv7", "aarch64", "amd64"],
  "homeassistant_api": true,
  "ports": {
    "8000/tcp": 8000,
    "9090/tcp": 9090
  }
}
```

### Вариант B: Docker Sidecar
Запуск рядом с HA в той же сети с доступом к API.

### Вариант C: External Server
Развёртывание на отдельном сервере с доступом к HA API по сети.

## Метрики успеха

- Время развёртывания: < 15 минут
- Время отката: < 5 минут
- Полнота бэкапа: 100% автоматизаций
- Zero downtime при переключении режимов
