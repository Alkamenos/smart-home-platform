# Production Dockerfile для Behavioral Platform
# ВАЖНО: требуется Python >= 3.12 — src/webui/app.py использует PEP 695
# (def _run_coroutine[T](...)), который не парсится на 3.11 (SyntaxError).
FROM python:3.12-slim

# Аргументы сборки
ARG BUILD_ENV=production

# Переменные окружения (устанавливаем рано для лучшего кэширования)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUILD_ENV=${BUILD_ENV} \
    CONFIG_PATH=/config/behavioral_platform \
    CONFIG_SEED_PATH=/app/instances/leonids_house \
    DATA_PATH=/data/behavioral_platform \
    PYTHONPATH=/app/src \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

# Рабочая директория
WORKDIR /app

# Установка системных зависимостей и очистка в один слой
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

# СЛОЙ 1: Копируем только зависимости (pyproject.toml) для кэширования
COPY pyproject.toml .
COPY README.md .

# СЛОЙ 2: Устанавливаем только зависимости проекта из pyproject.toml
# (не сам проект: src/ копируется ниже — слой зависимостей остаётся кэшируемым;
#  апгрейд pip убран — лишняя загрузка по нестабильной сети)
RUN pip install --no-cache-dir \
    $(python -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")

# СЛОЙ 3: Копируем исходный код (изменяется часто)
COPY src/ ./src/
# Конфигурация попадает в образ только как ПОСЕВ для тома: entrypoint
# переносит её в $CONFIG_PATH, если каталог тома пуст. Копировать сразу в
# $CONFIG_PATH нельзя — bind-mount всё равно замаскирует её пустым каталогом.
COPY instances/ ./instances/

# Скрипт старта: копируется отдельно, т.к. каталог deploy/ в образ целиком
# не переносится — нужен ровно один файл.
COPY deploy/docker/docker-entrypoint.sh ./deploy/docker/docker-entrypoint.sh
RUN chmod +x ./deploy/docker/docker-entrypoint.sh

# СЛОЙ 4: Каталоги для данных и конфигурации
# CONFIG_SEED_PATH — источник посева для пустого тома: из него entrypoint
# копирует СОДЕРЖИМОЕ каталога инстанса, поэтому CONFIG_PATH указывает
# прямо на manifest.yaml, как и заявлено в deploy/README.md и
# deploy/.env.example. Раньше CONFIG_PATH указывал на сам каталог инстанса,
# из-за чего в пути деплоя было зашито имя каталога.
# CONFIG_PATH обязан совпадать с точкой монтирования в docker-compose.prod.yml
# (/config/behavioral_platform) — это единственный путь, который переживает
# пересоздание контейнера. Раньше здесь стояло
# /config/instances/leonids_house: каталог не создавался и не монтировался,
# то есть конфигурация писалась в слой контейнера и терялась.
# Пользовательское имя каталога в путях деплоя недопустимо.
#
# Каталоги для данных и логов
RUN mkdir -p /data/behavioral_platform/logs \
    && mkdir -p /config/behavioral_platform

# Health check endpoint
EXPOSE 8125

# Запуск приложения.
# entrypoint переносит конфигурацию из образа в каталог тома, если тот пуст:
# bind-mount не наследует содержимое образа, поэтому без этого шага том
# оставался пустым.
ENTRYPOINT ["/app/deploy/docker/docker-entrypoint.sh"]
CMD ["python", "-m", "src.main"]
