"""Чтение и правка манифеста (спека 017, US5, FR-027).

Манифест — единственный источник конфигурации дома (конституция V), поэтому
правка идёт через то же хранилище, что и остальные пути: с валидацией, резервной
копией и защитой от молчаливой потери комнат и устройств.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from core.persistence.manifest_store import ManifestShrinkError
from webui.services.manifest_runtime import apply_manifest_to_runtime, prime_location_state


router = APIRouter(tags=["manifest"])


def _store(request: Request) -> Any:
    """Взять хранилище манифеста у приложения.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        Хранилище манифеста.

    Raises:
        HTTPException: 503, если хранилище недоступно.
    """
    store = getattr(request.app.state, "manifest_store", None)
    if store is None:
        raise HTTPException(
            status_code=503, detail="Хранилище манифеста недоступно: платформа не собрана"
        )
    return store


@router.get("/api/v1/manifest", response_class=JSONResponse)
async def get_manifest(request: Request) -> JSONResponse:
    """Отдать текущий манифест.

    Args:
        request: Входящий HTTP-запрос.

    Returns:
        JSON с манифестом и признаком несохранённых изменений; 503, если файл
        не читается.
    """
    store = _store(request)
    try:
        if store.current is None:
            store.load()
    except Exception as e:  # noqa: BLE001 — причина попадает в ответ
        return JSONResponse(
            {"error": f"Манифест не прочитан: {e}"},
            status_code=503,
        )
    return JSONResponse(
        {
            "manifest": store.current.model_dump(),
            "has_unsaved_changes": bool(store.has_unsaved_changes),
        }
    )


@router.put("/api/v1/manifest", response_class=JSONResponse)
async def put_manifest(request: Request, allow_removal: bool = Query(False)) -> JSONResponse:
    """Проверить и сохранить манифест.

    Args:
        request: Входящий HTTP-запрос с телом-манифестом.
        allow_removal: Разрешить запись, при которой из описания дома исчезают
            комнаты или устройства. По умолчанию запрещено: тихое уменьшение
            состава дома означает, что часть дома молча выпала из автоматики.
            Осознанное удаление (например, перенос устройства в другую комнату)
            передаёт флаг явно.

    Returns:
        ``{"status": "saved"}`` при успехе; ``400`` с ошибками по полям, если
        манифест не проходит валидацию; ``409``, если запись потеряла бы
        комнаты или устройства.
    """
    store = _store(request)
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 — тело может быть не JSON
        raise HTTPException(status_code=400, detail="Тело запроса не является JSON") from None

    try:
        model = store.model_type(**data)
    except ValidationError as exc:
        fields = [
            {
                "loc": ".".join(str(part) for part in error.get("loc", ())),
                "message": error.get("msg", "некорректное значение"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            {"error": "Манифест не принят проверкой", "fields": fields},
            status_code=400,
        )
    except Exception as e:  # noqa: BLE001 — прочие ошибки разбора
        return JSONResponse({"error": f"Манифест не разобран: {e}"}, status_code=400)

    store.current = model
    try:
        store.save(allow_removal=allow_removal)
    except ManifestShrinkError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)

    # Правка обязана дойти до работающей платформы без перезапуска (FR-027):
    # перечитываем манифест в рантайм. Неудача применения не отменяет запись
    # файла, но о ней сообщаем — молчаливое расхождение хуже предупреждения.
    container = getattr(request.app.state, "container", None)
    lifecycle_service = getattr(request.app.state, "lifecycle_service", None)
    warnings: list[str] = []
    try:
        apply_manifest_to_runtime(store, container, lifecycle_service)
        await prime_location_state(container)
    except Exception as exc:  # noqa: BLE001 — причина попадает в ответ
        warnings.append(f"Манифест сохранён, но не применён в рантайме: {exc}")

    return JSONResponse({"status": "saved", "warnings": warnings})
