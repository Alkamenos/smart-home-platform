# Стадия сборки фронтенда (спека 017): статический экспорт в out/.
# Закрепляем базовый образ по digest: тег lts-slim может смениться между сборками.
FROM node:lts-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS frontend
WORKDIR /frontend
# Node 26+ больше не поставляет corepack. Ставим pnpm явно — версия совпадает
# с packageManager в frontend/package.json (pnpm@10.0.0).
RUN npm install -g pnpm@10.0.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build


# Стадия зависимостей: lock-файл, без сборочного инструментария в runtime.
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30 AS deps

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
RUN pip install --no-cache-dir uv==0.13.0 \
    && uv sync --frozen --no-dev --no-install-project


# Production-образ: минимальные права, без компиляторов и pip-кэша.
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ARG BUILD_ENV=production

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BUILD_ENV=${BUILD_ENV} \
    CONFIG_PATH=/config/behavioral_platform \
    CONFIG_SEED_PATH=/app/instances/leonids_house_prod \
    DATA_PATH=/data/behavioral_platform \
    PYTHONPATH=/app/src \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp

WORKDIR /app

# Непривилегированный пользователь. UID/GID фиксированы: compose ссылается на
# них в user:, и смена молча сломала бы права на тома.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=deps /opt/venv /opt/venv
COPY src/ ./src/
# Статический экспорт фронтенда: копируется в образ и раздаётся платформой.
COPY --from=frontend /frontend/out ./frontend/out
ENV WEBUI_SERVE_FRONTEND=1
# Эталон конфигурации: entrypoint копирует его в том, если тот пуст.
COPY instances/ ./instances/
COPY deploy/docker/docker-entrypoint.sh ./deploy/docker/docker-entrypoint.sh
RUN chmod +x ./deploy/docker/docker-entrypoint.sh

# Каталоги для томов и права непривилегированного пользователя.
RUN mkdir -p /data/behavioral_platform/logs /config/behavioral_platform \
    && chown -R app:app /app /data /config /opt/venv

# Контейнер стартует от root только чтобы выровнять права на тома (bind-mount
# может принадлежать другому UID), затем entrypoint сбрасывает права через
# setpriv. Процесс приложения всегда работает от 10001 — см. docker-entrypoint.sh.
EXPOSE 8125

ENTRYPOINT ["/app/deploy/docker/docker-entrypoint.sh"]
CMD ["python", "-m", "src.main"]
