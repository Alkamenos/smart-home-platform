# Production Dockerfile для Behavioral Platform
FROM python:3.11-slim

# Аргументы сборки
ARG BUILD_ENV=production

# Переменные окружения (устанавливаем рано для лучшего кэширования)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUILD_ENV=${BUILD_ENV} \
    CONFIG_PATH=/config/instances/leonids_house \
    DATA_PATH=/data/behavioral_platform \
    PYTHONPATH=/app/src

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

# СЛОЙ 2: Устанавливаем зависимости
RUN pip install --upgrade pip && \
    pip install --no-cache-dir .

# СЛОЙ 3: Копируем исходный код (изменяется часто)
COPY src/ ./src/
COPY instances/ ./instances/

# СЛОЙ 4: Создание директорий для данных и логов
RUN mkdir -p /data/behavioral_platform/logs \
    && mkdir -p /config/behavioral_platform

# Health check endpoint
EXPOSE 8125

# Запуск приложения
CMD ["python", "-m", "src.main"]
