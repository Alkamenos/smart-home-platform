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

Для Docker-развёртывания файл конфигурации — `deploy/docker/.env`, и он
**единственный**. Compose читает его и как `env_file`, и для подстановки
`${...}`, а блок `environment:` в `docker-compose.prod.yml` намеренно не
дублирует операторские переменные — иначе значение из оболочки молча
перекрывало бы файл (проверено: `HA_TOKEN=... docker compose up -d` подменял
токен, и отличить это от значения в `.env` было невозможно).

```bash
cp deploy/docker/.env.example deploy/docker/.env
nano deploy/docker/.env   # укажите HA_TOKEN и HOME_ASSISTANT_ENCRYPTION_KEY
```

**Важно:** Получите токен в профиле пользователя HA → "Long-Lived Access Tokens"

### Шифрование токенов

Токены Home Assistant шифруются ключом Fernet. Ключ берётся из первого
доступного источника:

1. `HOME_ASSISTANT_ENCRYPTION_KEY` — если задана;
2. файл `ENCRYPTION_KEY_PATH`, по умолчанию `DATA_PATH/encryption.key`.

Если файла нет, он создаётся один раз, с правами `600`, и лежит в томе данных —
то есть переживает и перезапуск, и пересоздание контейнера. Задавать переменную
не обязательно: она нужна, только если ключ должен храниться вне тома.

**Файл ключа обязан попадать в резервные копии.** Без него сохранённые токены
не расшифровать — ключ не восстанавливается. `deploy.sh backup` копирует весь
каталог данных, поэтому ключ включается автоматически.

Если файл существует, но пуст или не читается, платформа **не создаёт новый
ключ**, а поднимает ошибку. Иначе она продолжила бы работу и зашифровала уже
сохранённые токены поверх прежних, то есть разрушила их безвозвратно.

Проверено запуском контейнера: после `down && up -d` ключ и токен не изменились;
при потере ключа источник не загружается с явной ошибкой, значение в
`sources.json` остаётся прежним, а после возврата ключа источник снова
доступен.

Сгенерировать свой ключ заранее:

```bash
python -c "from core.security.encryption import generate_encryption_key; print(generate_encryption_key())"
```

### 3. Создание директорий для данных

```bash
mkdir -p deploy/docker/config deploy/docker/data
```

Каталоги — именно `deploy/docker/...`, потому что compose монтирует тома
относительно каталога compose-файла:

| На хосте | В контейнере | Содержимое |
|---|---|---|
| `deploy/docker/config` | `/config/behavioral_platform` | `manifest.yaml` — конфигурация |
| `deploy/docker/data` | `/data/behavioral_platform` | состояния, источники, журнал |

При первом запуске `docker-entrypoint.sh` переносит конфигурацию из образа в
`deploy/docker/config`, если каталог пуст; последующие запуски её не трогают.
Каталоги `deploy/docker/config`, `deploy/docker/data` и `deploy/docker/backups`
в `.gitignore` — это рабочие данные, а не исходный код.

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
| `SHADOW_MODE` | Режим развёртывания. `false`/`0`/`no`/`off` — команды исполняются; всё остальное, включая **незаданную переменную** и опечатку, — режим тени, команды не исполняются | режим тени |
| `CONFIG_PATH` | Путь к конфигурации | `/config/behavioral_platform` |
| `DATA_PATH` | Путь к данным | `/data/behavioral_platform` |
| `WATCHDOG_INTERVAL_SEC` | Интервал проверок состояний автоматов | `60` |
| `WATCHDOG_HA_LOSS_SEC` | Порог потери связи с Home Assistant | `300` |
| `SYNC_STALE_SEC` | Порог устаревания синхронизации источника. Синхронизация запускается только вручную (`POST /api/v1/devices/sources/{id}/sync`), её дата не растёт сама; `/ready` сообщает о протухших данных по этому порогу | `86400` (сутки) |

### Структура директорий

```
deploy/
└── docker/
    ├── docker-compose.prod.yml
    ├── docker-entrypoint.sh      # посев конфигурации в том при первом старте
    ├── .env                      # секреты (НЕ в git)
    ├── .env.example              # образец .env (в git)
    ├── config/                   # ТОМ: конфигурация → /config/behavioral_platform
    │   └── manifest.yaml
    ├── data/                     # ТОМ: данные → /data/behavioral_platform
    │   ├── state.json            # состояния FSM
    │   ├── sources.json          # источники данных
    │   └── history.db            # журнал переходов
    └── backups/                  # копии deploy.sh backup
```

`CONFIG_PATH` и `DATA_PATH` заданы в `docker-compose.prod.yml` и указывают на
точки монтирования. Задавать их в `.env` нельзя: значение вне тома означает,
что данные переживут запуск, но не переживут `docker compose down && up -d` —
правки конфигурации будут молча откатываться к состоянию из образа.

### Резервные копии

Копия — это сжатый архив с манифестом, состояниями автоматов, источниками,
журналом и **файлом ключа шифрования**. Без ключа восстановление формально
произойдёт, а токены Home Assistant останутся нерасшифровываемыми, поэтому файл
включён в архив.

```bash
./deploy/scripts/deploy.sh backup              # создать копию и проверить её
./deploy/scripts/deploy.sh verify [файл]       # проверить целостность
./deploy/scripts/deploy.sh restore [файл]      # восстановить
```

Что делает каждая команда:

- `backup` собирает архив, считает SHA256 **внутри него** и сразу проверяет
  результат. Копия, которая не читается, удаляется: архив, который не
  восстановить, хуже отсутствия копии — он выглядит как защита;
- `verify` сверяет суммы. Обрезанный архив отвергает распаковка, а копию с
  подменённым содержимым — только сверка сумм;
- `restore` проверяет копию **до** остановки сервиса и до затирания данных,
  сохраняет текущее состояние в `pre_restore_*` и отменяется на битой копии.

Ротация: `BACKUP_KEEP` (по умолчанию 7) ограничивает число копий. Без неё
копии занимают диск и сами становятся причиной отказа платформы.

**Куда складывать копии.** По умолчанию — тот же хост, рядом с данными, и
`backup` об этом предупреждает: от потери диска или хоста это не защищает.
Для настоящей защиты укажите внешнее хранилище:

```bash
BACKUP_DEST_DIR=/mnt/nas/backups ./deploy/scripts/deploy.sh backup
```

**Регулярность.** Копии снимает cron хоста:

```cron
0 3 * * * BACKUP_DEST_DIR=/mnt/nas/backups /путь/к/репозиторию/deploy/scripts/deploy.sh backup >> /var/log/shp-backup.log 2>&1
```

Раз в сутки в 03:00. Потеря за день работы — цена, которую стоит выбрать
осознанно; если она неприемлема, поставьте чаще.

---

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
