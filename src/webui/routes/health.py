"""Обход дома: проблемы и реестр показаний (BACKLOG F6).

Две выдачи, и они не смешиваются:

* ``/api/v1/health`` — **проблемы** дома: прибор не отвечает, показание устарело,
  батарейка на исходе. То, что требует внимания человека.
* ``/api/v1/observation`` — **реестр показаний**: всё, что дом отдаёт, по локациям
  и комнатам манифеста. Чтение для ИИ («машинное зрение») и для человека:
  локации и комнаты названы разными словами и не путаются.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["health"])


def _service(request: Request) -> Any:
    """Взять обход дома из контейнера.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Служба обхода либо ``None``, если она не собрана.
    """
    container = getattr(request.app.state, "container", None)
    return getattr(container, "house_health", None)


async def _report(request: Request) -> dict[str, Any]:
    """Снимок обхода: последний или снятый сейчас.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Снимок обхода; пустой, если обход недоступен.
    """
    service = _service(request)
    if service is None:
        return {"generated_at": None, "sensor_count": 0, "problems": [], "areas": {}}
    return service.last_report or await service.sweep()


@router.get("/api/v1/health")
async def health(request: Request) -> JSONResponse:
    """Проблемы дома: что не отвечает, что молчит, что на исходе.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON с проблемами и числом датчиков в обходе.
    """
    report = await _report(request)
    return JSONResponse(
        {
            "generated_at": report.get("generated_at"),
            "sensor_count": report.get("sensor_count", 0),
            "problems": report.get("problems", []),
        }
    )


@router.get("/api/v1/observation")
async def observation(request: Request) -> JSONResponse:
    """Реестр показаний по локациям и комнатам.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON с реестром: группа → список показаний.
    """
    report = await _report(request)
    return JSONResponse(
        {
            "generated_at": report.get("generated_at"),
            "sensor_count": report.get("sensor_count", 0),
            "areas": report.get("areas", {}),
        }
    )
