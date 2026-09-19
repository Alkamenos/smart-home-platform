# Docker Entrypoint & Bootstrap Fix

**Приоритет:** CRITICAL
**Оценка:** 0.5 дня
**Категория:** Production Bugfixes
**Статус:** PLANNING

> Файл — ТЗ для ИИ-реализатора. Следуй инструкциям точно, сохраняя стиль проекта (loguru, asyncio, DI-контейнер).

## Цель

Docker-образ должен собираться, а контейнер — запускать платформу как демон: WebSocket-подключение к Home Assistant + HTTP-сервер для healthcheck/WebUI.

## Проблема (подтверждено аудитом кода)

1. `deploy/docker/Dockerfile` содержит `COPY requirements.txt .`, но файла `requirements.txt` в репозитории нет (зависимости в `pyproject.toml`). `docker build` падает с ошибкой `COPY failed`.
2. `CMD ["python", "-m", "src.main"]` указывает на несуществующий модуль: файла `src/main.py` нет. Единой точки входа, поднимающей event loop, адаптер и web-сервер, не существует.
3. Healthcheck в `docker-compose.prod.yml` ожидает HTTP на порту 8125, но никто сервер не поднимает.

## Инструкции для ИИ-реализатора

### 1. Переписать `deploy/docker/Dockerfile`

- База `python:3.11-slim`; `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1`; `WORKDIR /app`.
- Сначала `COPY pyproject.toml ./` и `RUN pip install --upgrade pip && pip install --no-cache-dir .` (кэшируемый слой зависимостей).
- Затем `COPY src/ ./src/` и `COPY instances/ ./instances/`.
- `EXPOSE 8125`; `CMD ["python", "-m", "src.main"]`.
- Удалить все упоминания `requirements.txt`.

### 2. Создать `src/main.py`

Структура (импорты адаптировать под фактическую раскладку модулей):

```python
import asyncio, os, signal
import uvicorn
from loguru import logger
from src.bootstrap import bootstrap_platform
from src.webui.app import create_app


async def run_platform(config_dir: str) -> None:
    manifest = os.path.join(config_dir, "manifest.yaml")
    ctx = bootstrap_platform(manifest)  # DI-контейнер
    await ctx.adapter.start()  # WebSocket к HA (фоново)
    app = create_app(manifest)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=os.environ.get("WEBUI_HOST", "0.0.0.0"),
            port=int(os.environ.get("WEBUI_PORT", "8125")),
            log_level="warning",
            access_log=False,
        )
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: setattr(server, "should_exit", True))
    try:
        await server.serve()
    finally:
        await ctx.adapter.stop()
        await ctx.fsm.shutdown()  # сохранение состояний FSM


if __name__ == "__main__":
    config_dir = os.environ.get("CONFIG_PATH", "instances/leonids_house")
    asyncio.run(run_platform(config_dir))
```

Требования:

- SIGTERM/SIGINT обязаны приводить к graceful shutdown (остановка адаптера, сохранение состояний FSM, закрытие сессий).
- Loguru: `logger.remove()` + handler с уровнем из ENV `LOG_LEVEL` (default INFO), формат с timestamp.
- Если `bootstrap_platform` асинхронная — использовать `await` соответственно.

### 3. Зависимости и health

- Убедиться, что `uvicorn` есть в `pyproject.toml` (`[project].dependencies`); при отсутствии добавить `uvicorn>=0.27`.
- Проверить `GET /health` в `src/webui/routes.py`: должен возвращать 200 и JSON `{"status":"ok"}`; при отсутствии — добавить.

## Файлы

| Файл | Действие |
|---|---|
| `deploy/docker/Dockerfile` | переписать |
| `src/main.py` | создать |
| `pyproject.toml` | добавить uvicorn (если нет) |
| `src/webui/routes.py` | проверить/добавить `/health` |

## Критерии успеха

- [ ] `docker build -f deploy/docker/Dockerfile -t smart-home-platform:v3 .` проходит
- [ ] `docker compose -f deploy/docker/docker-compose.prod.yml up -d` — контейнер стабилен (нет restart-loop)
- [ ] `curl -fsS http://localhost:8125/health` → 200
- [ ] В логах видно успешное подключение к HA WebSocket
- [ ] `docker stop` → graceful shutdown без "Unclosed client session" в логах
