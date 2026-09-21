"""FastAPI router for Web UI routes."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from loguru import logger

from src.core.persistence.event_store import EventStore


if TYPE_CHECKING:
    pass


router = APIRouter()

# Setup templates
template_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(template_dir))

# Initialize EventStore
event_store = EventStore()


@router.get("/health", response_class=HTMLResponse)
async def health_check(request: Request) -> HTMLResponse:
    """Health check endpoint.

    Args:
        request: FastAPI request object.

    Returns:
        Simple HTML response indicating service health.
    """
    return templates.TemplateResponse(
        request,
        "health.html",
        {"status": "healthy"},
    )


@router.get("/api/fsm/{entity_id}/diagram", response_class=Response)
async def get_fsm_diagram(entity_id: str) -> Response:
    """Generate FSM diagram for a device.

    Args:
        entity_id: Device entity ID.

    Returns:
        JSON with Mermaid diagram definition.
    """
    try:
        # For now, return a simple Mermaid diagram
        # In production, this would load from manifest and use FSMVisualizer
        mermaid_diagram = f"""stateDiagram-v2
    [*] --> OFF
    OFF --> ON: motion_detected
    ON --> OFF: no_motion
    state {entity_id} {{
        OFF
        ON
    }}"""

        return Response(
            content=json.dumps({"diagram": mermaid_diagram}),
            media_type="application/json",
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
    """Dashboard page with event charts.

    Args:
        request: FastAPI request object.

    Returns:
        Dashboard HTML page with Chart.js graphs.
    """
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"title": "Dashboard"},
    )


@router.get("/api/history/activity-heatmap")
async def get_activity_heatmap() -> dict:
    """Get activity heatmap data aggregated by hour of day.

    Returns:
        JSON data for heatmap visualization (hour x day_of_week).
    """
    # Mock data for now - will be replaced with EventStore aggregation
    # Format: array of 7 days (Mon-Sun), each with 24 hours
    import random

    random.seed(42)  # For consistent mock data

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    heatmap_data = []

    for day in days:
        day_hours = []
        for hour in range(24):
            # Simulate higher activity during morning and evening
            base_activity = 5
            if 7 <= hour <= 9:  # Morning peak
                base_activity += 15
            elif 18 <= hour <= 22:  # Evening peak
                base_activity += 20
            elif 0 <= hour <= 6:  # Night low
                base_activity = 2

            # Add some randomness
            activity = max(0, base_activity + random.randint(-3, 3))
            day_hours.append(activity)

        heatmap_data.append(
            {
                "day": day,
                "values": day_hours,
            }
        )

    return {
        "days": days,
        "hours": list(range(24)),
        "data": heatmap_data,
    }


@router.get("/api/events/history")
async def get_events_history() -> dict:
    """Get event history data for charts.

    Returns:
        JSON data for Chart.js visualization.
    """
    # Get real events from EventStore
    events = event_store.get_events(limit=100)

    # Aggregate events by hour
    from collections import defaultdict

    hourly_counts = defaultdict(int)

    current_time = time.time()
    hours_24 = 24 * 60 * 60

    for event in events:
        # Calculate which hour bucket this event falls into (relative to now)
        hours_ago = (current_time - event.timestamp) / hours_24
        if hours_ago <= 1:  # Last 24 hours
            hour_bucket = int((1 - hours_ago) * 24) % 24
            hourly_counts[hour_bucket] += 1

    # Build labels and data
    labels = [f"{h:02d}:00" for h in range(24)]
    data_values = [hourly_counts.get(h, 0) for h in range(24)]

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Events (Last 24h)",
                "data": data_values,
                "borderColor": "#0d6efd",
                "tension": 0.1,
                "fill": False,
            },
        ],
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
async def get_ai_suggestions() -> list[dict]:
    """Get AI suggestions (pending, accepted, rejected).

    Returns:
        List of suggestion records. If empty, returns mock suggestions for demo.
    """
    suggestions = event_store.get_suggestions()

    # If no suggestions in DB, generate mock data for demonstration
    if not suggestions:
        import random

        random.seed(42)

        mock_suggestions = [
            {
                "id": "sugg_001",
                "timestamp": time.time() - random.randint(3600, 86400),
                "entity_id": "light.living_room",
                "suggestion_type": "behavior_adjustment",
                "description": "Turn on living room light at 19:00 instead of 18:30 based on sunset patterns",
                "reasoning": "Historical data shows manual overrides occur 80% of the time at 19:00",
                "confidence": 0.85,
                "status": "pending",
            },
            {
                "id": "sugg_002",
                "timestamp": time.time() - random.randint(7200, 172800),
                "entity_id": "thermostat.main",
                "suggestion_type": "energy_optimization",
                "description": "Reduce heating by 2°C during 10:00-16:00 when house is empty",
                "reasoning": "Motion sensors show no activity during these hours on weekdays",
                "confidence": 0.92,
                "status": "pending",
            },
            {
                "id": "sugg_003",
                "timestamp": time.time() - random.randint(86400, 259200),
                "entity_id": "light.kitchen",
                "suggestion_type": "automation_creation",
                "description": "Create automation: turn on kitchen light when motion detected between 6:00-8:00",
                "reasoning": "Pattern detected: manual activation every morning at 6:30-7:00",
                "confidence": 0.78,
                "status": "accepted",
            },
        ]
        return mock_suggestions

    return suggestions


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
        event_store.update_suggestion_status(
            suggestion_id=suggestion_id,
            status=new_status,
            responded_at=time.time(),
        )

        return {"status": "success", "message": f"Suggestion {suggestion_id} {new_status}"}

    except Exception as e:
        logger.error(f"Failed to respond to suggestion {suggestion_id}: {e}")
        return {"error": str(e)}, 500
