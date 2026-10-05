#!/bin/bash
# Скрипт безопасного развертывания Behavioral Platform
# Поддерживает: deploy, rollback, status, health-check

set -e

# Конфигурация
PLATFORM_NAME="behavioral-platform"

# Путь к compose-файлу задаётся переменной окружения. Раньше он был зашит
# литералом, из-за чего скрипт нельзя было направить на другое развёртывание —
# ни в другое окружение, ни в изолированный каталог для тестов. Тесты при этом
# НЕ ПАДАЛИ, а молча работали с настоящими каталогами развёртывания, то есть
# вызывали `restore` и трогали живые данные. Переменная окружения — не удобство,
# а условие безопасности: без неё скрипт неотличим от того, что пишет в
# боевую директорию.
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-./deploy/docker/docker-compose.prod.yml}"

# Каталоги данных и конфигурации задаются ОТНОСИТЕЛЬНО КАТАЛОГА COMPOSE-ФАЙЛА,
# потому что именно относительно него compose монтирует тома:
#   volumes: ./config → /config/behavioral_platform
#            ./data   → /data/behavioral_platform
# Относительные пути в compose всегда отсчитываются от каталога compose-файла,
# а не от текущего каталога.
#
# Раньше здесь стояло CONFIG_DIR="./config" и DATA_DIR="./data" — от корня
# репозитория. Последствия были неочевидны:
#   * каталога ./config в корне репозитория вообще нет, поэтому конфигурация
#     (manifest.yaml) в резервную копию НЕ ПОПАДАЛА;
#   * ./data в корне — протухший каталог от локальных запусков, том его не
#     использует. Бэкап копировал данные, которых нет в работающей платформе,
#     а rollback восстанавливал их не туда.
# Проверено запуском `deploy.sh backup`: манифеста в копии не было, состояния
# были из ./data, тогда как живое состояние лежит в deploy/docker/data.
COMPOSE_DIR="$(cd "$(dirname "$DOCKER_COMPOSE_FILE")" && pwd)"
CONFIG_DIR="$COMPOSE_DIR/config"
DATA_DIR="$COMPOSE_DIR/data"
BACKUP_DIR="$COMPOSE_DIR/backups"
SHADOW_MODE="${SHADOW_MODE:-false}"

# Куда складывать архивы копий.
#
# По умолчанию — тот же хост, рядом с данными. Это НЕ защита от потери диска
# или хоста, поэтому `backup` об этом предупреждает: иначе бэкап выглядит
# защитой, которой нет. Для настоящей защиты задайте `BACKUP_DEST_DIR` на
# сетевой каталог, внешний диск или иное хранилище.
BACKUP_DEST_DIR="${BACKUP_DEST_DIR:-$BACKUP_DIR}"
# Сколько последних копий хранить. Без ротации копии занимают диск, и бэкап
# становится причиной отказа платформы из-за нехватки места.
BACKUP_KEEP="${BACKUP_KEEP:-7}"

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
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local dest="$BACKUP_DEST_DIR"
    local staging
    staging="$(mktemp -d)"
    local archive="$dest/backup_$timestamp.tar.gz"

    log_info "Создание резервной копии в $archive..."

    mkdir -p "$dest"

    if [ "$dest" = "$BACKUP_DIR" ]; then
        log_warn "Копия создаётся на том же хосте, что и данные (каталог $dest)."
        log_warn "От потери диска или хоста это НЕ защищает."
        log_warn "Задайте BACKUP_DEST_DIR на внешнее хранилище: $0 backup"
    fi

    # Каталоги переносятся под именами config/ и data/ независимо от того, где
    # они лежат на хосте: путь восстановления не должен зависеть от того, как
    # размечены тома.
    # COPYFILE_DISABLE=1 убирает служебные файлы `._*`, которые macOS создаёт
    # рядом с каждым скопированным файлом при переносе расширенных атрибутов.
    # В архив они попадать не должны: это мусор, который раздувает копию и
    # ломает проверку целостности при переносе на Linux.
    if [ -d "$CONFIG_DIR" ]; then
        COPYFILE_DISABLE=1 cp -r "$CONFIG_DIR" "$staging/config"
    fi
    if [ -d "$DATA_DIR" ]; then
        COPYFILE_DISABLE=1 cp -r "$DATA_DIR" "$staging/data"
    fi

    if [ ! -d "$staging/config" ] && [ ! -d "$staging/data" ]; then
        log_error "Нечего копировать: нет ни каталога конфигурации, ни каталога данных"
        log_error "Ожидались: $CONFIG_DIR и $DATA_DIR"
        rm -rf "$staging"
        return 1
    fi

    # Суммы внутри архива, а не рядом с ним: копия, перенесённая в другое
    # хранилище, должна проверяться на месте, без внешнего файла.
    if command -v sha256sum >/dev/null 2>&1; then
        ( cd "$staging" && find . -type f ! -name SHA256SUMS -print0 \
            | sort -z \
            | xargs -0 sha256sum > SHA256SUMS ) 2>/dev/null || log_warn "Не удалось посчитать суммы"
    else
        log_warn "sha256sum недоступен: контрольные суммы не рассчитаны"
    fi

    # Члены архива перечисляются явно: `tar -C ... .` даёт имена с префиксом
    # `./`, и проверка содержимого копии снаружи её не находит.
    local members=()
    [ -d "$staging/config" ] && members+=("config")
    [ -d "$staging/data" ] && members+=("data")
    members+=("SHA256SUMS")
    COPYFILE_DISABLE=1 tar -czf "$archive" -C "$staging" "${members[@]}"
    rm -rf "$staging"

    # Копия считается годной только после проверки собственной целостности.
    # Архив, который не читается, хуже отсутствия копии: он выглядит как
    # защита и обнаруживается при восстановлении.
    if ! verify_archive "$archive"; then
        log_error "Созданный архив не прошёл проверку целостности: $archive"
        return 1
    fi

    prune_old_backups

    log_info "Резервная копия создана и проверена: $archive"
    echo "$archive"
}

# Проверить целостность архива: читаемость и совпадение сумм
verify_archive() {
    local archive="$1"

    if [ ! -f "$archive" ]; then
        log_error "Архив не найден: $archive"
        return 1
    fi

    if ! tar -tzf "$archive" >/dev/null 2>&1; then
        log_error "Архив не читается: $archive"
        return 1
    fi

    if ! tar -xzOf "$archive" SHA256SUMS >/dev/null 2>&1; then
        log_error "В архиве нет файла сумм SHA256SUMS: $archive"
        return 1
    fi

    local staging
    staging="$(mktemp -d)"
    tar -xzf "$archive" -C "$staging" 2>/dev/null
    if ( cd "$staging" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
        rm -rf "$staging"
        return 0
    fi
    rm -rf "$staging"
    log_error "Контрольные суммы не совпали: $archive"
    return 1
}

# Проверить последнюю (или указанную) копию
verify_backup() {
    local archive="${1:-}"
    if [ -z "$archive" ]; then
        archive=$(latest_archive)
    fi
    if [ -z "$archive" ]; then
        log_error "Резервных копий не найдено в $BACKUP_DEST_DIR"
        return 1
    fi
    log_info "Проверка целостности: $archive"
    if verify_archive "$archive"; then
        log_info "Копия целостна: $archive"
        return 0
    fi
    log_error "Копия повреждена: $archive"
    return 1
}

# Восстановить данные и конфигурацию из архива
restore_backup() {
    local archive="$1"

    if [ -z "$archive" ]; then
        archive=$(latest_archive)
    fi
    if [ -z "$archive" ]; then
        log_error "Резервных копий не найдено в $BACKUP_DEST_DIR"
        return 1
    fi

    # Проверка ДО остановки сервиса и до затирания: восстановление из битой
    # копии хуже, чем отсутствие восстановления, — оно выглядит как помощь.
    if ! verify_archive "$archive"; then
        log_error "Восстановление отменено: копия не прошла проверку целостности"
        return 1
    fi

    # Имя через mktemp, а не по секундам: два восстановления в одну секунду давали
    # одинаковое имя, и `cp -r` в уже существующий каталог вкладывал данные в
    # самих себя (`config/config/manifest.yaml`). Страховочная копия от этого
    # становилась нечитаемой — то есть переставала быть страховкой.
    local safety
    safety="$(mktemp -d "$BACKUP_DIR/pre_restore_XXXXXXXX")"
    [ -d "$CONFIG_DIR" ] && cp -r "$CONFIG_DIR" "$safety/config"
    [ -d "$DATA_DIR" ] && cp -r "$DATA_DIR" "$safety/data"
    log_info "Текущие данные сохранены в $safety"

    local staging
    staging="$(mktemp -d)"
    tar -xzf "$archive" -C "$staging"

    [ -d "$staging/config" ] && cp -r "$staging/config/." "$CONFIG_DIR/"
    [ -d "$staging/data" ] && cp -r "$staging/data/." "$DATA_DIR/"
    rm -rf "$staging"

    log_info "Восстановлено из $archive"
    log_warn "Если платформа работала во время восстановления, перезапустите её:"
    log_warn "  docker compose -f $DOCKER_COMPOSE_FILE restart $PLATFORM_NAME"
}

# Удалить старые копии сверх лимита
prune_old_backups() {
    local keep="${BACKUP_KEEP:-7}"
    local count
    count=$(find "$BACKUP_DEST_DIR" -maxdepth 1 -name 'backup_*.tar.gz' 2>/dev/null | wc -l | tr -d ' ')
    if [ "$count" -le "$keep" ]; then
        return 0
    fi
    local remove=$(( count - keep ))
    log_info "Ротация копий: удаляю $remove из $count (лимит $keep)"
    find "$BACKUP_DEST_DIR" -maxdepth 1 -name 'backup_*.tar.gz' 2>/dev/null \
        | sort | head -n "$remove" | while read -r old; do
            log_info "  удаляю $old"
            rm -f "$old"
        done
}

latest_archive() {
    find "$BACKUP_DEST_DIR" -maxdepth 1 -name 'backup_*.tar.gz' 2>/dev/null | sort | tail -n 1
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

    if [ ! -d "$backup_path/config" ] && [ ! -d "$backup_path/data" ]; then
        log_error "В $backup_path нет ни конфигурации, ни данных — откат невозможен."
        log_error "Похоже, копия создана старой версией скрипта (неверные пути)."
        exit 1
    fi

    # Сервис останавливается ДО восстановления файлов.
    #
    # Раньше порядок был обратным: сначала `rm -rf` каталогов, затем `down`.
    # Это не проявлялось только потому, что пути указывали на протухший ./data
    # в корне репозитория, который платформа не использует. С настоящими путями
    # контейнер продолжал бы писать в уже удалённый каталог, а восстановление
    # перемешивалось бы с живыми записями (в том числе в SQLite-журнал).
    log_info "Остановка сервиса перед восстановлением..."
    if command -v docker-compose &> /dev/null; then
        docker-compose -f "$DOCKER_COMPOSE_FILE" down
    else
        docker compose -f "$DOCKER_COMPOSE_FILE" down
    fi

    # Откат удаляет данные, поэтому текущее состояние сохраняется отдельно.
    safety_path="$BACKUP_DIR/pre_rollback_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$safety_path"
    [ -d "$CONFIG_DIR" ] && cp -r "$CONFIG_DIR" "$safety_path/config"
    [ -d "$DATA_DIR" ] && cp -r "$DATA_DIR" "$safety_path/data"
    log_info "Текущее состояние сохранено в $safety_path (откат можно отменить вручную)"

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
        docker-compose -f "$DOCKER_COMPOSE_FILE" up -d
    else
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
        verify)
            verify_backup "${2:-}"
            ;;
        restore)
            restore_backup "${2:-}"
            ;;
        help|*)
            echo "Usage: $0 {deploy|shadow|rollback|status|health|backup|verify|restore}"
            echo ""
            echo "Commands:"
            echo "  deploy   - Развернуть платформу (production или shadow mode)"
            echo "  shadow   - Развернуть в shadow mode для тестирования"
            echo "  rollback - Откатиться к предыдущей версии"
            echo "  status   - Показать статус сервиса"
            echo "  health   - Проверить здоровье сервиса"
            echo "  backup   - Создать сжатую резервную копию с проверкой целостности"
            echo "  verify   - Проверить целостность копии (последней или указанной)"
            echo "  restore  - Восстановить данные из копии (последней или указанной)"
            echo ""
            echo "Environment Variables:"
            echo "  SHADOW_MODE=true  - Включить shadow mode"
            echo "  HA_TOKEN          - Токен доступа к Home Assistant"
            ;;
    esac
}

main "$@"
