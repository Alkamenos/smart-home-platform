"""FastAPI router for Web UI routes."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from loguru import logger


if TYPE_CHECKING:
    pass


router = APIRouter()

# Setup templates
template_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(template_dir))


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
        HTML page with Mermaid.js rendering the FSM diagram.
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

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>body {{ margin: 0; padding: 20px; font-family: sans-serif; }}</style>
</head>
<body>
    <div class="mermaid">{mermaid_diagram}</div>
    <script>mermaid.initialize({{ startOnLoad: true }});</script>
</body>
</html>"""

        return Response(content=html_content, media_type="text/html")

    except Exception as e:
        logger.error(f"Failed to generate FSM diagram for {entity_id}: {e}")
        return Response(content=f"Error: {e}", status_code=500)


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


@router.get("/api/events/history")
async def get_events_history() -> dict:
    """Get event history data for charts.

    Returns:
        JSON data for Chart.js visualization.
    """
    # Mock data for now - will be replaced with EventStore integration
    return {
        "labels": ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
        "datasets": [
            {
                "label": "Motion Events",
                "data": [5, 2, 15, 8, 12, 20],
                "borderColor": "#0d6efd",
                "tension": 0.1,
            },
            {
                "label": "Light Commands",
                "data": [3, 1, 10, 5, 8, 15],
                "borderColor": "#ffc107",
                "tension": 0.1,
            },
        ],
    }
