"""FastAPI application factory for Web UI."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from fastapi import FastAPI
from loguru import logger

from core.persistence.atomic import atomic_write_text
from core.persistence.manifest_store import ManifestStore

from .models import ManifestModel


if TYPE_CHECKING:
    from core.container import Container
    from services.device_service import DeviceService


DEFAULT_USER_ID = "admin_user"
"""Идентификатор пользователя по умолчанию для запросов интерфейса."""

DEFAULT_USER_IS_ADMIN = "true"
"""Права администратора по умолчанию для запросов интерфейса."""


def _resolve_default_user() -> tuple[str, bool]:
    """Определяет идентичность пользователя по умолчанию из окружения.

    В WebUI нет аутентификации (spec 006, D-008), поэтому идентичность,
    с которой интерфейс обращается к защищённым адресам, задаётся окружением
    и настраивается при развёртывании.

    Returns:
        Пара ``(user_id, is_admin)``.
    """
    import os

    user_id = os.getenv("WEBUI_DEFAULT_USER_ID", DEFAULT_USER_ID)
    is_admin = os.getenv("WEBUI_DEFAULT_USER_ADMIN", DEFAULT_USER_IS_ADMIN).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return user_id, is_admin


def _run_device_service_hydration(device_service: DeviceService) -> int:
    """Синхронно выполняет асинхронную гидратацию устройств (spec 006, FR-004).

    Args:
        device_service: Сервис устройств.

    Returns:
        Количество загруженных устройств.
    """
    return _run_coroutine(device_service.hydrate_from_persistence())


class LogStore:
    """In-memory storage for application logs."""

    def __init__(self, max_logs: int = 5000) -> None:
        """Initialize the log store.

        Args:
            max_logs: Maximum number of logs to keep in memory.
        """
        self.logs: list[dict] = []
        self.max_logs = max_logs

    def add(self, level: str, message: str, timestamp: str | None = None) -> None:
        """Add a log entry.

        Args:
            level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            message: Log message.
            timestamp: ISO format timestamp (auto-generated if not provided).
        """
        import datetime

        if timestamp is None:
            timestamp = datetime.datetime.now(datetime.UTC).isoformat()

        log_entry = {
            "timestamp": timestamp,
            "level": level.upper(),
            "message": message,
        }

        self.logs.insert(0, log_entry)  # Add to beginning for newest first
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[: self.max_logs]

    def get_logs(self, limit: int = 1000) -> list[dict]:
        """Get logs.

        Args:
            limit: Maximum number of logs to return.

        Returns:
            List of log entries.
        """
        return self.logs[:limit]

    def clear(self) -> None:
        """Clear all logs."""
        self.logs = []


def _get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def _run_coroutine[T](coroutine: Coroutine[Any, Any, T]) -> T:
    """Выполняет корутину из синхронного обработчика FastAPI.

    ``create_app`` и хендлеры, отдающие HTML-фрагменты, синхронны по сигнатуре,
    хотя часть сервисов асинхронна. Если уже есть работающий event loop,
    корутина выполняется в отдельном потоке со своим циклом.

    Args:
        coroutine: Корутина для выполнения.

    Returns:
        Результат корутины.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def _load_sources_for_form(persistence: Any) -> list[dict[str, Any]]:
    """Загружает список источников для выпадающего списка в форме устройства.

    Args:
        persistence: Менеджер хранения (может быть None).

    Returns:
        Список словарей ``{id, name, url}``; пустой список, если источников нет
        или хранилище недоступно.
    """
    if persistence is None or not hasattr(persistence, "sources"):
        return []

    try:
        sources = _run_coroutine(persistence.sources.load_all_sources())
    except Exception as e:
        logger.warning(f"Не удалось загрузить источники для формы: {e}")
        return []

    return [
        {"id": str(source.id), "name": source.name, "url": str(source.url).rstrip("/")}
        for source in sources or []
    ]


def _sync_manifest_store(manifest_store: Any, core_manifest: Any) -> None:
    """Синхронизирует веб-представление манифеста с ядерным.

    Веб-слой historically держал собственную копию манифеста, из-за чего
    изменения, сделанные сервисом жизненного цикла, не были видны на
    странице (spec 006, D-007). Здесь представление пересобирается из
    ядерного манифеста — единственного источника состава дома.

    Args:
        manifest_store: Хранилище манифеста веб-приложения.
        core_manifest: Ядерная модель манифеста.
    """
    manifest_store.current = ManifestModel(**core_manifest.model_dump())


def _parse_behaviors_from_form(form_data: Any, behavior_model: Any) -> list[Any]:
    """Извлекает поведения устройства из данных формы.

    Args:
        form_data: Данные формы (``await request.form()``).
        behavior_model: Модель поведения веб-слоя.

    Returns:
        Список поведений устройства.
    """
    behaviors = []
    index = 0
    while f"behavior_template_{index}" in form_data:
        behaviors.append(
            behavior_model(
                template=form_data[f"behavior_template_{index}"],
                priority=int(form_data[f"behavior_priority_{index}"]),
                params=json.loads(form_data.get(f"behavior_params_{index}", "{}")),
            )
        )
        index += 1
    return behaviors


def create_app(
    manifest_path: str | None = None, container_instance: Container | None = None
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        manifest_path: Path to the manifest file to edit.
                      If None, uses default instance path.
        container_instance: Optional shared Container instance from main.py.
                           If provided, uses its adapter for discovery routes.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="Smart Home Manifest Editor",
        description="Web UI for editing smart home FSM manifests",
        version="1.0.0",
    )

    # Include routes
    from .routes import router

    app.include_router(router)

    # Include discovery routes
    from .routes_discovery import router as discovery_router

    app.include_router(discovery_router)

    # Состояние и история локаций (спека 016, FR-007). Регистрируется рядом с
    # основными маршрутами: снимок читается у платформы, история — из журнала.
    from .routes.locations import router as locations_router

    app.include_router(locations_router)

    # Спека 017: идентичность интерфейса, агрегат первого экрана «Дом» и канал
    # живых изменений состояния. Регистрируются до монтирования статики, чтобы
    # маршруты API имели приоритет над раздачей фронтенда.
    from .routes.events import router as events_router
    from .routes.logs import router as logs_router
    from .routes.manifest import router as manifest_router
    from .routes.overview import router as overview_router
    from .routes.session import router as session_router
    from .routes.ws_events import router as ws_events_router

    app.include_router(session_router)
    app.include_router(overview_router)
    app.include_router(events_router)
    app.include_router(manifest_router)
    app.include_router(logs_router)
    app.include_router(ws_events_router)

    # US4/T004: регистрация middleware контроля доступа (идентификация на
    # device-endpoints). Регистрируется ДО включения маршрутов — действует
    # на все пути, но проверяет только область /api/v1/devices/**
    from webui.middleware_access_control import DeviceAccessMiddleware

    app.add_middleware(DeviceAccessMiddleware)

    # Include device management routes (T051-T057)
    try:
        from .routes.devices import access_control, devices, sources, websocket

        # sources ДО devices: GET /api/v1/devices/sources иначе перехватывается
        # маршрутом devices GET /api/v1/devices/{device_id} → 422 (Known Issue #4)
        app.include_router(sources.router)
        app.include_router(devices.router)
        app.include_router(access_control.router)
        app.include_router(websocket.router)
        logger.info("Device management routes registered")
    except ImportError as e:
        logger.warning(f"Could not import device routes: {e}")

    # Default manifest path - resolve relative to project root
    if manifest_path is None:
        manifest_path = str(_get_project_root() / "instances" / "leonids_house" / "manifest.yaml")

    # Initialize manifest store
    manifest_store = ManifestStore(manifest_path, ManifestModel)
    # Хранилище доступно маршрутам правки манифеста (спека 017, US5): правка идёт
    # через тот же экземпляр, что и остальные пути, иначе записи разойдутся.
    app.state.manifest_store = manifest_store

    # Initialize log store
    log_store = LogStore()
    # Технические логи доступны разделу «Система» (спека 017, US6).
    app.state.log_store = log_store

    # Add initial info log
    log_store.add("INFO", "Web UI started")

    # Configure loguru to log to both console and log store
    def loguru_sink(message):
        """Custom loguru sink to write logs to log store."""
        try:
            # Extract log level and message from loguru record
            record = message.record
            level = record["level"].name
            msg = record["message"]
            timestamp = record["time"].isoformat()
            log_store.add(level, msg, timestamp)
        except Exception:
            pass  # Silently ignore logging errors to avoid recursion

    # Remove default handlers and add custom ones
    logger.remove()
    logger.add(loguru_sink, format="{message}", level="DEBUG")
    # Keep console logging for development
    logger.add(
        lambda msg: print(msg, end=""),
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="INFO",
    )
    # The adapter is already connected in main.py via ctx.adapter.start()
    _container = None
    try:
        from core.container import Container

        from .routes_discovery import init_discovery_routes

        # Use provided container or create a new one
        if container_instance is not None:
            _container = container_instance
            logger.info("Using shared container instance for discovery routes")
        else:
            _container = Container(manifest_path=manifest_path)
            _ = _container.build()  # Trigger initialization
            logger.info("Created new container instance for discovery routes")

        # Справочник комнат для формы импорта: важно передать то же хранилище
        # манифеста, что использует остальной интерфейс, иначе список комнат
        # разойдётся с реальным.
        init_discovery_routes(manifest_path, manifest_store=manifest_store)
        logger.info("Room reference initialized")
    except Exception as e:
        logger.warning(f"Could not initialize room reference: {e}")

    # Expose the platform container to routers that need it (e.g. FSM diagrams)
    app.state.container = _container

    # Initialize device management services (T049-T060)
    try:
        from core.events.event_bus import EventBus
        from services.device_service import DeviceService
        from webui.routes.devices.websocket import make_fsm_broadcaster

        # Одна шина событий на процесс: веб-слой и ядро должны видеть одни и те
        # же события, иначе переходы автоматов не доходят до интерфейса, а все
        # события device.* уходят в пустоту (FR-006, R-07).
        event_bus = _container.event_bus if _container is not None else EventBus()
        persistence = None

        try:
            from core.persistence.manager import PersistenceManager

            # Каталог данных не передаётся: PersistenceManager сам берёт его
            # из DATA_PATH (см. core/persistence/paths.py). Раньше здесь стояло
            # data_dir="data", из-за чего путь неявно закреплялся за относительным
            # путём от WORKDIR, и в контейнере данные писались внутрь слоя
            # образа вместо смонтированного тома (Known Issue #44).
            persistence = PersistenceManager()
        except ImportError as e:
            logger.warning(
                f"Could not initialize PersistenceManager: {e}. Running with limited functionality."
            )

        device_service = DeviceService(
            event_bus=event_bus,
            persistence_module=persistence,
            ha_adapter=_container.adapter if _container is not None else None,
            engine=_container.fsm if _container is not None else None,
            event_router=_container.event_router if _container is not None else None,
            # Манифест нужен только при включённом SYNC_FILTER_MANIFEST_ONLY:
            # фильтр берёт из него список сущностей, которые синхронизация
            # должна обновлять. Без флага он игнорируется, поэтому передача
            # манифеста ничего не меняет в поведении по умолчанию.
            manifest=_container.manifest if _container is not None else None,
        )

        # Обработчик изменения состояния устройства существовал, но ни на что
        # не подписывался: состояние обновлялось только синхронизацией (FR-007).
        device_service.subscribe_state_changes()

        # Гидратация из постоянного хранилища: без неё список устройств был
        # пуст до первой синхронизации, а добавленные устройства исчезали
        # после перезапуска (spec 006, FR-004)
        try:
            hydrated = _run_device_service_hydration(device_service)
        except Exception as e:
            logger.warning(f"Device hydration skipped: {e}")
            hydrated = 0
        if hydrated:
            logger.info(f"Restored {hydrated} device(s) from persistence")

        # Сервис жизненного цикла: единственная точка, выполняющая операцию
        # «манифест → хранилище → машины состояний → маршрутизация» (spec 006).
        # Работает с ядерным манифестом из контейнера — тем же объектом, на
        # котором построены фабрика FSM и карта маршрутизации.
        lifecycle_service = None
        if _container is not None:
            try:
                from services.device_lifecycle import DeviceLifecycleService

                lifecycle_service = DeviceLifecycleService(
                    manifest=_container.manifest,
                    device_service=device_service,
                    factory=_container.factory,
                    engine=_container.fsm,
                    event_router=_container.event_router,
                    persistence=persistence,
                    manifest_store=manifest_store,
                )
            except Exception as e:
                logger.warning(f"Device lifecycle service unavailable: {e}")

        # Живые обновления состояний автоматов: мост состояний получает раздатчик,
        # который разрешает entity_id в идентификатор устройства и рассылает
        # переход подписанным соединениям с проверкой прав (FR-024, FR-025).
        fsm_broadcaster = make_fsm_broadcaster(device_service)
        bridge = _container.fsm_bridge if _container is not None else None
        if bridge is not None:
            bridge.set_broadcaster(fsm_broadcaster)

        app.state.event_bus = event_bus
        app.state.persistence = persistence
        app.state.device_service = device_service
        app.state.lifecycle_service = lifecycle_service
        app.state.fsm_broadcaster = fsm_broadcaster

        # Живые показания датчиков для первого экрана «Дом» (спека 017, FR-012):
        # менеджер канала событий подписывается на шину. Идентичность и подписки
        # проверяются при каждой доставке, соединение без auth ничего не получает.
        from webui.routes.ws_events import event_stream, on_state_change

        app.state.event_stream = event_stream
        event_bus.subscribe("state_change", on_state_change)
        default_user_id, default_user_is_admin = _resolve_default_user()
        app.state.default_user_id = default_user_id
        app.state.default_user_is_admin = default_user_is_admin
        logger.info(
            f"Device management services initialized (default user: {default_user_id}, "
            f"admin: {default_user_is_admin})"
        )
    except Exception as e:
        logger.warning(f"Could not initialize device services: {e}")

    # Спека 017: статический интерфейс. Собранный фронтенд (``frontend/out``)
    # раздаётся тем же процессом с того же origin — CORS не нужен, а API
    # зарегистрирован выше и потому имеет приоритет. Монтирование идёт до старых
    # серверных страниц: новый интерфейс заменяет их (старые удаляются отдельной
    # задачей). Если сборки нет, платформа работает как раньше.
    from .static_serving import mount_frontend, should_serve_frontend

    if should_serve_frontend() and mount_frontend(app):
        logger.info("Frontend static export mounted (frontend/out)")

    # Живые обновления состояний автоматов доставляются каналом устройств
    # /api/v1/ws/devices: в нём есть идентификация пользователя, подписки и
    # проверка прав при каждой доставке. Прежний /ws/live не имел ни того, ни
    # другого, а его раздатчик не вызывался ниоткуда, поэтому эндпоинт выведен
    # из эксплуатации (spec 007, FR-025, R-08).

    return app


def _load_manifest(path: str) -> dict:
    """Load manifest from YAML file.

    Args:
        path: Path to the manifest file.

    Returns:
        Manifest data as dictionary.
    """
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_manifest(path: str, data: dict) -> None:
    """Save manifest to YAML file.

    Args:
        path: Path to the manifest file.
        data: Manifest data to save.
    """
    atomic_write_text(path, yaml.dump(data, default_flow_style=False, sort_keys=False))
