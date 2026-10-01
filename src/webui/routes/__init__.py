"""FastAPI router for Web UI routes."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from loguru import logger

from src.core.persistence.event_store import EventStore
from src.webui.models import build_all_fsm_state_views


if TYPE_CHECKING:
    pass


router = APIRouter()

# Setup templates
# Шаблоны лежат в src/webui/templates/, а этот модуль — в src/webui/routes/
template_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(template_dir))

# Initialize EventStore
event_store = EventStore()


@router.get("/health", response_class=JSONResponse)
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint (FR-002 спецификации 003).

    Возвращает JSON-контракт готовности сервиса, который используется
    Docker healthcheck-ом через ``python -m src.cli.health_check``.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON ``{"status": "ok"}`` со статусом 200.
    """
    return JSONResponse({"status": "ok"})


def _mermaid_state_id(raw: str) -> str:
    """Sanitize an identifier so Mermaid accepts it as a state id.

    Args:
        raw: Raw entity id, e.g. ``light.kitchen_lighting_10``.

    Returns:
        Identifier safe to use in a stateDiagram-v2.
    """
    return re.sub(r"[^0-9a-zA-Z_]", "_", raw)


# Сколько триггеров показывать в одной метке ребра до усечения.
MAX_TRIGGERS_IN_EDGE_LABEL = 2


def _state_alias(entity: str, state: str) -> str:
    """Собрать уникальный идентификатор состояния для Mermaid.

    Args:
        entity: Идентификатор автомата, уже очищенный от недопустимых символов.
        state: Имя состояния.

    Returns:
        Идентификатор, безопасный для ``stateDiagram-v2``.
    """
    return f"{entity}__{_mermaid_state_id(state)}"


def _guard_label(guard: Any) -> str:
    """Получить читаемое имя условия перехода.

    Args:
        guard: Условие перехода или None.

    Returns:
        Имя условия либо пустая строка для анонимных обёрток.
    """
    if guard is None:
        return ""
    name = getattr(guard, "__name__", "")
    if name and name not in ("guard", "guard_fn", "combined_guard"):
        return name
    return ""


def _combine_edge_labels(buckets: dict[str, list[str]]) -> str:
    """Собрать метку ребра из триггеров и условий.

    Одинаковые условия объединяются в один суффикс, а длинные списки
    усекаются: разметка Mermaid не справляется с очень длинными метками рёбер
    и не отображает схему вовсе (FR-029).

    Args:
        buckets: Условие перехода → список меток триггеров.

    Returns:
        Метка ребра.
    """
    parts: list[str] = []
    plain = buckets.get("", [])
    if plain:
        shown = plain[:MAX_TRIGGERS_IN_EDGE_LABEL]
        if len(plain) > len(shown):
            shown.append(f"+{len(plain) - len(shown)}")
        parts.append(", ".join(shown))

    for guard, triggers in buckets.items():
        if not guard:
            continue
        shown = triggers[:MAX_TRIGGERS_IN_EDGE_LABEL]
        suffix = f" [{guard}]"
        if len(triggers) > len(shown):
            shown.append(f"+{len(triggers) - len(shown)}")
        parts.append(f"{', '.join(shown)}{suffix}")

    return " / ".join(parts)


def _build_mermaid_state_diagram(definitions: list[Any]) -> str:
    """Build a Mermaid stateDiagram-v2 from FSM definitions.

    Каждому состоянию присваивается собственный идентификатор через
    ``state "Имя" as идентификатор``. Прежняя форма ``машина : СОСТОЯНИЕ`` не
    разбирается Mermaid: интерфейс показывал ошибку парсинга вместо схемы
    (spec 007, FR-029).

    Args:
        definitions: FSMDefinition objects to render.

    Returns:
        Mermaid diagram source.
    """
    lines = ["stateDiagram-v2"]
    initial_targets: list[str] = []
    single = len(definitions) == 1

    for definition in definitions:
        entity = _mermaid_state_id(definition.entity_id)
        target = definition.target_device_id or definition.entity_id
        if single:
            lines.append(f"title {_mermaid_state_id(target)}")

        states: list[str] = [
            definition.initial_state,
            *(t.to_state for t in definition.transitions),
        ]
        for state in dict.fromkeys(states):
            lines.append(f'state "{state}" as {_state_alias(entity, state)}')

        initial = _state_alias(entity, definition.initial_state)
        initial_targets.append(initial)

        # Несколько триггеров между одной парой состояний объединяются в одно
        # ребро: параллельные дублирующиеся рёбра не разводит разметка Mermaid,
        # и схема не отображалась вовсе (FR-029).
        edges: dict[tuple[str, str], dict[str, list[str]]] = {}
        for transition in definition.transitions:
            label = transition.trigger
            if transition.priority:
                label = f"{label} (p{transition.priority})"
            guard_name = _guard_label(transition.guard)

            bucket = edges.setdefault((transition.from_state, transition.to_state), {})
            triggers = bucket.setdefault(guard_name, [])
            if label not in triggers:
                triggers.append(label)

        for (from_state, to_state), buckets in edges.items():
            lines.append(
                f"{_state_alias(entity, from_state)} --> {_state_alias(entity, to_state)}"
                f" : {_combine_edge_labels(buckets)}"
            )

    for initial in initial_targets:
        lines.append(f"[*] --> {initial}")

    return "\n".join(lines)


@router.get("/api/fsm/state", response_class=JSONResponse)
async def get_fsm_state(request: Request) -> JSONResponse:
    """Отдать текущее состояние всех автоматов (FR-017).

    Состояние берётся из движка на момент запроса, поэтому ответ не устаревает
    относительно последнего обработанного перехода (FR-018). Отсутствие
    автоматов — пустой список, а недоступность движка — ошибка 503 с описанием:
    эти ситуации нельзя смешивать (FR-020, FR-021).

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON ``{"count": N, "states": [...]}`` либо JSON с описанием ошибки.
    """
    container = getattr(request.app.state, "container", None)
    fsm_engine = getattr(container, "fsm", None)
    if fsm_engine is None:
        return JSONResponse({"error": "FSM engine is not available"}, status_code=503)

    allowed_devices = await _resolve_accessible_device_ids(request)
    views = build_all_fsm_state_views(fsm_engine, allowed_devices)

    return JSONResponse(
        {
            "count": len(views),
            "states": [view.model_dump() for view in views],
        }
    )


async def _resolve_accessible_device_ids(request: Request) -> set[str] | None:
    """Определить устройства, доступные пользователю запроса (FR-038).

    Ответ фильтруется по существующей модели доступа: пользователь видит
    состояния только тех устройств, к которым у него есть права. Если сервис
    устройств недоступен, фильтрация не применяется — иначе раздел выглядел бы
    пустым из-за сбоя, а не из-за отсутствия прав.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Множество доступных идентификаторов устройств. ``None`` означает «без
        фильтрации», а пустое множество — у пользователя нет доступных
        устройств, поэтому раздел должен быть пуст.
    """
    user_id = request.headers.get("X-User-ID")
    device_service = getattr(request.app.state, "device_service", None)
    if not user_id or device_service is None:
        return None

    is_admin = request.headers.get("X-Is-Admin", "false").lower() == "true"
    if is_admin:
        return None

    try:
        devices = await device_service.get_user_accessible_devices(user_id)
    except Exception as e:  # noqa: BLE001 - фильтрация не должна ломать раздел
        logger.warning(f"Could not resolve device access for {user_id}: {e}")
        return None

    return {device.ha_entity_id for device in devices if device.ha_entity_id}


@router.get("/api/fsm/{entity_id}/diagram", response_class=Response)
async def get_fsm_diagram(request: Request, entity_id: str) -> Response:
    """Generate FSM diagram for a device (FR-029).

    Отдаётся чистая Mermaid-строка: прежний JSON-конверт вставлялся в страницу
    как текст, и пользователь видел служебный JSON вместо схемы. Текущее
    состояние в схему не встраивается — оно приходит разделом состояний и живыми
    сообщениями и подсвечивается на клиенте (FR-030, R-09).

    Args:
        request: FastAPI request object.
        entity_id: Device entity ID.

    Returns:
        Mermaid-строка (text/plain); ошибки — JSON с описанием.
    """
    try:
        container = getattr(request.app.state, "container", None)
        if container is None:
            return Response(
                content=json.dumps({"error": "Platform container is not available"}),
                status_code=503,
                media_type="application/json",
            )

        fsm_engine = container.fsm
        definitions = [
            definition
            for definition in fsm_engine._definitions.values()
            if entity_id in (definition.entity_id, definition.target_device_id)
        ]

        if not definitions:
            return Response(
                content=json.dumps(
                    {
                        "error": (
                            f"No FSM registered for '{entity_id}'. "
                            "The device may have no behaviors configured, "
                            "or its templates failed to load."
                        )
                    }
                ),
                status_code=404,
                media_type="application/json",
            )

        return Response(
            content=_build_mermaid_state_diagram(definitions),
            media_type="text/plain; charset=utf-8",
        )

    except Exception as e:
        logger.error(f"Failed to generate FSM diagram for {entity_id}: {e}")
        return Response(
            content=json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json",
        )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Dashboard page with event charts and FSM diagrams.

    Args:
        request: FastAPI request object.

    Returns:
        Dashboard HTML page with Chart.js graphs and FSM diagrams.
    """
    # Collect all devices from manifest
    devices = []
    try:
        # Try to get container from app state
        container = request.app.state.container
        if container and hasattr(container, "manifest") and container.manifest:
            for room in container.manifest.rooms:
                for device in room.devices:
                    devices.append(
                        {
                            "id": device.id,
                            "type": device.type,
                            "name": device.name,
                            "room": room.id,
                            "behaviors": [
                                {
                                    "template": b.template,
                                    "priority": b.priority,
                                }
                                for b in (device.behaviors or [])
                            ],
                        }
                    )
    except Exception as e:
        logger.warning(f"Could not load devices for dashboard: {e}")

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "title": "Dashboard",
            "devices": devices,
        },
    )


@router.get("/api/history/activity-heatmap")
async def get_activity_heatmap() -> dict:
    """Карта активности по фактическим записям (FR-033, FR-036).

    Раньше значения выдумывались генератором с фиксированным зерном, поэтому
    график выглядел правдоподобно и менялся от запуска к запуску (решение D-2).
    Теперь карта считается по журналу переходов и событий, а при отсутствии
    записей возвращает ``has_data: false`` вместо правдоподобных нулей.

    Returns:
        JSON с днями, часами, значениями и признаком наличия данных.
    """
    try:
        return event_store.get_activity_heatmap()
    except Exception as e:
        logger.error(f"Failed to build activity heatmap: {e}")
        return {"days": [], "hours": [], "data": [], "has_data": False, "error": str(e)}


@router.get("/api/events/history")
async def get_events_history() -> dict:
    """История событий за сутки по настенным часам (FR-033, FR-036).

    Корзины считаются по часам суток (``0`` — полночь). Прежние корзины
    считались «часов назад» при подписях от ``00:00``, из-за чего график
    отображался задом наперёд.

    Returns:
        JSON с подписями, набором данных и признаком наличия данных.
    """
    try:
        history = event_store.get_hourly_history(hours=24)
    except Exception as e:
        logger.error(f"Failed to build events history: {e}")
        return {"labels": [], "datasets": [], "has_data": False, "error": str(e)}

    return {
        "labels": history["labels"],
        "datasets": [
            {
                "label": "Events (Last 24h)",
                "data": history["data"],
                "borderColor": "#0d6efd",
                "tension": 0.1,
                "fill": False,
            }
        ],
        "has_data": history["has_data"],
    }


@router.get("/api/overrides")
async def get_overrides() -> list[dict]:
    """Get active manual overrides.

    Returns:
        List of active override records.
    """
    return event_store.get_active_overrides()


@router.post("/api/override")
async def create_override(request: Request) -> Any:
    """Create a new manual override.

    Args:
        request: FastAPI request with JSON body containing:
            - entity_id: Device entity ID
            - action: Override action (e.g., "force_on", "force_off")
            - duration: Duration in seconds

    Returns:
        Status message.
    """
    try:
        data = await request.json()
        entity_id = data.get("entity_id")
        action = data.get("action")
        duration = data.get("duration", 3600)  # Default 1 hour

        if not entity_id or not action:
            return {"error": "Missing entity_id or action"}, 400

        current_time = time.time()
        expires_at = current_time + duration

        event_store.save_override(
            entity_id=entity_id,
            started_at=current_time,
            expires_at=expires_at,
            reason=f"Manual override: {action}",
            user_id="webui",
        )

        return {"status": "success", "message": f"Override created for {entity_id}"}

    except Exception as e:
        logger.error(f"Failed to create override: {e}")
        return {"error": str(e)}, 500


@router.delete("/api/override/{entity_id}")
async def remove_override(entity_id: str) -> Any:
    """Remove a manual override.

    Args:
        entity_id: Device entity ID to remove override for.

    Returns:
        Status message.
    """
    try:
        event_store.remove_override(entity_id)
        return {"status": "success", "message": f"Override removed for {entity_id}"}

    except Exception as e:
        logger.error(f"Failed to remove override: {e}")
        return {"error": str(e)}, 500


@router.get("/api/ai/suggestions")
async def get_ai_suggestions() -> dict:
    """Подсказки из журнала (FR-035, FR-036).

    Раньше при пустом журнале возвращались три выдуманные записи, не совпадавшие
    по форме с настоящими строками, поэтому интерфейс всегда показывал вымысел.
    Выдумка удалена полностью (решение D-2): пустой раздел честнее правдоподобной
    лжи.

    Returns:
        JSON со списком подсказок и признаком наличия данных.
    """
    try:
        suggestions = event_store.get_suggestions()
    except Exception as e:
        logger.error(f"Failed to load AI suggestions: {e}")
        return {"suggestions": [], "has_data": False, "error": str(e)}

    return {"suggestions": suggestions, "has_data": bool(suggestions)}


@router.post("/api/ai/suggestion/{suggestion_id}/respond")
async def respond_to_suggestion(suggestion_id: str, request: Request) -> Any:
    """Respond to an AI suggestion (accept/reject).

    Args:
        suggestion_id: ID of the suggestion to respond to.
        request: FastAPI request with JSON body containing:
            - action: 'accept' or 'reject'

    Returns:
        Status message.
    """
    try:
        data = await request.json()
        action = data.get("action")

        if action not in ["accept", "reject"]:
            return {"error": "Action must be 'accept' or 'reject'"}, 400

        # Update suggestion status in EventStore
        new_status = "accepted" if action == "accept" else "rejected"
        # Лишний аргумент responded_at приводил к TypeError и ответу 500:
        # метод такого параметра не принимает (spec 007, FR-036).
        event_store.update_suggestion_status(
            suggestion_id=suggestion_id,
            status=new_status,
        )

        return {"status": "success", "message": f"Suggestion {suggestion_id} {new_status}"}

    except Exception as e:
        logger.error(f"Failed to respond to suggestion {suggestion_id}: {e}")
        return {"error": str(e)}, 500


@router.get("/api/templates")
async def list_templates() -> dict[str, Any]:
    """Get all available FSM templates.

    Returns:
        JSON with list of templates and their parameters.
    """
    from ..template_loader import get_template_loader

    try:
        loader = get_template_loader()
        templates_dict = loader.load_all()

        result = {
            "templates": [template.to_dict() for template in templates_dict.values()],
            "count": len(templates_dict),
        }
        return result
    except Exception as e:
        logger.error(f"Failed to load templates: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/templates/{template_name}")
async def get_template(template_name: str) -> dict[str, Any]:
    """Get a specific template by name.

    Args:
        template_name: Name of the template (without .yaml extension).

    Returns:
        JSON with template metadata and parameters.

    Raises:
        HTTPException: If template not found or error loading templates.
    """
    from ..template_loader import get_template_loader

    try:
        loader = get_template_loader()
        templates_dict = loader.load_all()

        if template_name not in templates_dict:
            raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")

        template = templates_dict[template_name]
        return template.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template {template_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
