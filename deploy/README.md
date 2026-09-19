# Инструкция по развертыванию Behavioral Platform в Home Assistant

## 📋 Предварительные требования

- Docker и Docker Compose установлены на хосте с Home Assistant
- Home Assistant версии 2023.x или новее
- Long-Lived Access Token для HA
- Свободное место на диске: ~500MB

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
cd /config
git clone <repository_url> behavioral_platform
cd behavioral_platform
```

### 2. Настройка переменных окружения

```bash
cp deploy/.env.example .env
nano .env  # Отредактируйте файл, указав ваш HA_TOKEN
```

**Важно:** Получите токен в профиле пользователя HA → "Long-Lived Access Tokens"

### 3. Создание директорий для данных

```bash
mkdir -p deploy/config deploy/data
```

### 4. Развертывание в Shadow Mode (рекомендуется сначала)

```bash
# Тестовый запуск без влияния на основную систему
export SHADOW_MODE=true
./deploy/scripts/deploy.sh shadow
```

Проверьте логи:
```bash
docker logs -f behavioral-platform
```

### 5. Production развертывание

После успешного тестирования в shadow mode:

```bash
./deploy/scripts/deploy.sh deploy
```

## 📖 Основные команды

| Команда | Описание |
|---------|----------|
| `./deploy/scripts/deploy.sh deploy` | Развернуть платформу |
| `./deploy/scripts/deploy.sh shadow` | Развернуть в shadow mode |
| `./deploy/scripts/deploy.sh status` | Показать статус сервиса |
| `./deploy/scripts/deploy.sh health` | Проверить здоровье |
| `./deploy/scripts/deploy.sh backup` | Создать резервную копию |
| `./deploy/scripts/deploy.sh rollback` | Откатиться к предыдущей версии |

## 🔧 Конфигурация

### Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `HA_URL` | URL Home Assistant | `http://localhost:8123` |
| `HA_TOKEN` | Токен доступа к HA | *(требуется)* |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `SHADOW_MODE` | Режим безопасного тестирования | `false` |
| `CONFIG_PATH` | Путь к конфигурации | `/config/behavioral_platform` |
| `DATA_PATH` | Путь к данным | `/data/behavioral_platform` |

### Структура директорий

```
deploy/
├── config/           # Конфигурационные файлы
│   ├── manifest.yaml
│   └── behaviors/
├── data/             # Данные платформы
│   ├── states/       # Сохраненные состояния FSM
│   ├── logs/         # Логи платформы
│   └── metrics/      # Метрики
└── backups/          # Автоматические резервные копии
```

## 🛡️ Безопасность

### Shadow Mode

Shadow mode позволяет тестировать изменения без влияния на основную систему:

- Все команды выполняются в "теневом" режиме
- Состояния не сохраняются постоянно
- Идеально для тестирования новых поведений

```bash
export SHADOW_MODE=true
./deploy/scripts/deploy.sh shadow
```

### Graceful Fallback

При ошибках платформа автоматически:

1. Создает резервную копию перед обновлением
2. Откатывается к предыдущей версии при неудаче
3. Сохраняет работоспособность основной системы HA

## 📊 Мониторинг

### Проверка статуса

```bash
./deploy/scripts/deploy.sh status
```

### Health Check Endpoint

```bash
curl http://localhost:8125/health
```

### Просмотр логов

```bash
# Последние 100 строк
docker logs --tail 100 behavioral-platform

# Real-time просмотр
docker logs -f behavioral-platform

# С фильтрацией по уровню
docker logs behavioral-platform 2>&1 | grep ERROR
```

## 🔄 Обновление

### Плановое обновление

```bash
# 1. Создать резервную копию
./deploy/scripts/deploy.sh backup

# 2. Обновить код
git pull origin main

# 3. Развернуть новую версию
./deploy/scripts/deploy.sh deploy
```

### Экстренный откат

```bash
./deploy/scripts/deploy.sh rollback
```

## 🐛 Troubleshooting

### Сервис не запускается

1. Проверьте логи: `docker logs behavioral-platform`
2. Убедитесь, что HA_TOKEN корректен
3. Проверьте доступность HA: `curl http://localhost:8123`

### Ошибки подключения к HA

- Убедитесь, что используется `network_mode: host`
- Проверьте правильность HA_URL
- Убедитесь, что токен действителен

### Проблемы с памятью

```bash
# Проверка использования ресурсов
docker stats behavioral-platform

# Очистка старых контейнеров
docker system prune -f
```

## 📞 Поддержка

При возникновении проблем:

1. Проверьте документацию
2. Изучите логи платформы
3. Создайте issue с описанием проблемы и логами

## 🎯 Следующие шаги

После успешного развертывания:

1. Сгенерируйте манифест: `python -m src.cli.manifest_generator`
2. Создайте дашборды: `python -m src.cli.dashboard_generator`
3. Настройте поведения в `deploy/config/behaviors/`
