# Production Dockerfile для Behavioral Platform
FROM python:3.11-slim

# Аргументы сборки
ARG BUILD_ENV=production

# Рабочая директория
WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование зависимостей
COPY requirements.txt .
COPY requirements-dev.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY src/ ./src/
COPY config/ ./config/

# Создание директорий для данных и логов
RUN mkdir -p /data/behavioral_platform/logs \
    && mkdir -p /config/behavioral_platform

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUILD_ENV=${BUILD_ENV} \
    CONFIG_PATH=/config/behavioral_platform \
    DATA_PATH=/data/behavioral_platform

# Health check endpoint
EXPOSE 8125

# Запуск приложения
CMD ["python", "-m", "src.main"]
