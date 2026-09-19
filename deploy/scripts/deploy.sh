#!/bin/bash
# Скрипт безопасного развертывания Behavioral Platform
# Поддерживает: deploy, rollback, status, health-check

set -e

# Конфигурация
PLATFORM_NAME="behavioral-platform"
CONFIG_DIR="./config"
DATA_DIR="./data"
DOCKER_COMPOSE_FILE="./deploy/docker/docker-compose.prod.yml"
BACKUP_DIR="./backups"
SHADOW_MODE="${SHADOW_MODE:-false}"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Проверка зависимостей
check_dependencies() {
    log_info "Проверка зависимостей..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker не установлен. Установите Docker и попробуйте снова."
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose не установлен. Установите Docker Compose и попробуйте снова."
        exit 1
    fi

    if [ -z "$HA_TOKEN" ]; then
        log_warn "HA_TOKEN не установлен. Убедитесь, что токен передан через переменную окружения."
    fi

    log_info "Зависимости проверены."
}

# Создание резервной копии
create_backup() {
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_path="$BACKUP_DIR/backup_$timestamp"

    log_info "Создание резервной копии в $backup_path..."

    mkdir -p "$backup_path"

    # Копирование конфигурации
    if [ -d "$CONFIG_DIR" ]; then
        cp -r "$CONFIG_DIR" "$backup_path/config"
    fi

    # Копирование данных (состояния)
    if [ -d "$DATA_DIR" ]; then
        cp -r "$DATA_DIR" "$backup_path/data"
    fi

    log_info "Резервная копия создана: $backup_path"
    echo "$backup_path"
}

# Проверка здоровья сервиса
health_check() {
    log_info "Проверка здоровья сервиса..."

    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if docker ps --filter "name=$PLATFORM_NAME" --filter "status=running" | grep -q "$PLATFORM_NAME"; then
            # Дополнительная проверка через health check endpoint
            if curl -s http://localhost:8125/health > /dev/null 2>&1; then
                log_info "Сервис здоров и готов к работе."
                return 0
            fi
        fi

        log_warn "Попытка $attempt/$max_attempts: Сервис еще не готов..."
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "Сервис не прошел проверку здоровья после $max_attempts попыток."
    return 1
}

# Развертывание в shadow mode
deploy_shadow() {
    log_info "Развертывание в SHADOW MODE (безопасный режим)..."

    export SHADOW_MODE=true

    # Запуск в shadow mode
    if command -v docker-compose &> /dev/null; then
        docker-compose -f "$DOCKER_COMPOSE_FILE" up -d
    else
        docker compose -f "$DOCKER_COMPOSE_FILE" up -d
    fi

    if health_check; then
        log_info "Shadow mode активирован. Тестирование изменений..."
        log_warn "ВНИМАНИЕ: Изменения не влияют на основную систему."
        return 0
    else
        log_error "Не удалось запустить сервис в shadow mode."
        return 1
    fi
}

# Production развертывание
deploy_production() {
    log_info "Развертывание в PRODUCTION режиме..."

    export SHADOW_MODE=false

    # Создание резервной копии перед развертыванием
    local backup_path=$(create_backup)

    # Остановка текущего сервиса
    log_info "Остановка текущего сервиса..."
    if command -v docker-compose &> /dev/null; then
        docker-compose -f "$DOCKER_COMPOSE_FILE" stop || true
    else
        docker compose -f "$DOCKER_COMPOSE_FILE" stop || true
    fi

    # Сборка и запуск новой версии
    log_info "Сборка и запуск новой версии..."
    if command -v docker-compose &> /dev/null; then
        docker-compose -f "$DOCKER_COMPOSE_FILE" build --no-cache
        docker-compose -f "$DOCKER_COMPOSE_FILE" up -d
    else
        docker compose -f "$DOCKER_COMPOSE_FILE" build --no-cache
        docker compose -f "$DOCKER_COMPOSE_FILE" up -d
    fi

    # Проверка здоровья
    if health_check; then
        log_info "Production развертывание успешно завершено."
        return 0
    else
        log_error "Production развертывание не удалось. Выполняется откат..."
        rollback "$backup_path"
        return 1
    fi
}

# Откат к предыдущей версии
rollback() {
    local backup_path="${1:-}"

    if [ -z "$backup_path" ]; then
        # Поиск последней резервной копии
        backup_path=$(ls -td "$BACKUP_DIR"/backup_* 2>/dev/null | head -n1)

        if [ -z "$backup_path" ]; then
            log_error "Резервные копии не найдены. Невозможно выполнить откат."
            exit 1
        fi

        log_info "Использование последней резервной копии: $backup_path"
    fi

    log_warn "Выполняется откат к версии из $backup_path..."

    # Восстановление конфигурации
    if [ -d "$backup_path/config" ]; then
        rm -rf "$CONFIG_DIR"
        cp -r "$backup_path/config" "$CONFIG_DIR"
        log_info "Конфигурация восстановлена."
    fi

    # Восстановление данных
    if [ -d "$backup_path/data" ]; then
        rm -rf "$DATA_DIR"
        cp -r "$backup_path/data" "$DATA_DIR"
        log_info "Данные восстановлены."
    fi

    # Перезапуск сервиса
    log_info "Перезапуск сервиса..."
    if command -v docker-compose &> /dev/null; then
        docker-compose -f "$DOCKER_COMPOSE_FILE" down
        docker-compose -f "$DOCKER_COMPOSE_FILE" up -d
    else
        docker compose -f "$DOCKER_COMPOSE_FILE" down
        docker compose -f "$DOCKER_COMPOSE_FILE" up -d
    fi

    if health_check; then
        log_info "Откат успешно завершен."
        return 0
    else
        log_error "Откат не удался. Требуется ручное вмешательство."
        return 1
    fi
}

# Статус сервиса
show_status() {
    log_info "Статус сервиса:"

    if command -v docker-compose &> /dev/null; then
        docker-compose -f "$DOCKER_COMPOSE_FILE" ps
    else
        docker compose -f "$DOCKER_COMPOSE_FILE" ps
    fi

    echo ""
    log_info "Использование ресурсов:"
    docker stats --no-stream "$PLATFORM_NAME" 2>/dev/null || echo "Сервис не запущен"
}

# Основная функция
main() {
    local command="${1:-help}"

    case "$command" in
        deploy)
            check_dependencies
            if [ "$SHADOW_MODE" = "true" ]; then
                deploy_shadow
            else
                deploy_production
            fi
            ;;
        shadow)
            check_dependencies
            deploy_shadow
            ;;
        rollback)
            rollback "${2:-}"
            ;;
        status)
            show_status
            ;;
        health)
            health_check
            ;;
        backup)
            create_backup
            ;;
        help|*)
            echo "Usage: $0 {deploy|shadow|rollback|status|health|backup}"
            echo ""
            echo "Commands:"
            echo "  deploy   - Развернуть платформу (production или shadow mode)"
            echo "  shadow   - Развернуть в shadow mode для тестирования"
            echo "  rollback - Откатиться к предыдущей версии"
            echo "  status   - Показать статус сервиса"
            echo "  health   - Проверить здоровье сервиса"
            echo "  backup   - Создать резервную копию"
            echo ""
            echo "Environment Variables:"
            echo "  SHADOW_MODE=true  - Включить shadow mode"
            echo "  HA_TOKEN          - Токен доступа к Home Assistant"
            ;;
    esac
}

main "$@"
