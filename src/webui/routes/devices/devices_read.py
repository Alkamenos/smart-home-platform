"""Read-only device routes (spec 018, T059)."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from webui.models import build_all_fsm_state_views
from webui.routes.devices.deps import (
    get_device_service,
    get_lifecycle_service,
    get_sync_history,
)
from webui.routes.devices.devices_common import (
    _ROLE_VIEWER,
    _is_admin_request,
    _require_access_or_403,
)
from webui.routes.devices.devices_models import DeviceEventResponse, DeviceResponse
from webui.routes.devices.devices_views import (
    _build_device_behaviors_map,
    _build_device_fsm_views,
    _device_behaviors,
    _to_device_response,
    _to_event_response,
)
from webui.services.decisions import decision_view


logger = logging.getLogger(__name__)
router = APIRouter()


async def get_devices(
    request: Request,
    source_id: UUID | None = None,
    ha_entity_id: str | None = None,
    x_user_id: str | None = Header(None),
) -> list[DeviceResponse]:
    """Получает список всех доступных пользователю устройств.

    Видимость определяется признаком администратора и, для остальных, записями
    о доступе (T069, contracts/access-control-api.md §2):

    - ``X-Is-Admin: true`` → все устройства установки без фильтрации по
      записям: администратор глобальный, персональные записи ему не нужны
      (spec 004 spec.md:128, data-model.md:38). Тот же обход, что даёт
      одиночным операциям `_require_access_or_403` — иначе в одном модуле
      действовали бы два противоречивых правила «кто имеет право видеть
      устройство», а дефолтная идентичность WebUI (администратор,
      ``src/webui/app.py``) получала бы от своего же API пустой список.
    - иначе — только устройства, к которым у пользователя есть запись о доступе
      (``get_user_accessible_devices``); без ``X-User-ID`` пустой список.

    Фильтры по ``source_id`` и ``ha_entity_id`` применяются поверх в обоих
    случаях. Фильтр по ``ha_entity_id`` был молчаливо игнорируем: параметр
    приходил в запрос, но на выборку не влиял, и вызывающий код получал все
    устройства, считая, что получил суженную выборку (#74).

    Список берётся из единого источника — DeviceService (spec 006, FR-003):
    раньше роут читал временный словарь, который был пуст после перезапуска
    и не содержал устройств, загруженных синхронизацией.

    Args:
        request: HTTP запрос (для получения DeviceService и признака админа)
        source_id: Опциональный фильтр по источнику
        ha_entity_id: Опциональный фильтр по entity_id в Home Assistant
        x_user_id: ID пользователя из заголовка X-User-ID

    Returns:
        Список устройств, доступных пользователю
    """
    try:
        device_service = get_device_service(request)
        is_admin = _is_admin_request(request)

        if is_admin:
            # Обход администратора: полный список без чтения записей доступа.
            devices = await device_service.list_devices()
        else:
            # Если нет ID пользователя, возвращаем пустой список
            if not x_user_id:
                logger.debug("Запрос GET /api/v1/devices без X-User-ID - возвращаю пустой список")
                return []

            # T069: фильтруем по доступу пользователя (важнее source_id)
            devices = await device_service.get_user_accessible_devices(x_user_id)

        # Фильтры применяются поверх фильтра доступа, а не вместо него.
        if source_id:
            devices = [device for device in devices if device.source_id == source_id]
        if ha_entity_id:
            devices = [device for device in devices if device.ha_entity_id == ha_entity_id]

        logger.info(
            f"Получен список {len(devices)} устройств для пользователя {x_user_id} "
            f"(администратор: {is_admin})"
        )
        fsm_views = _build_device_fsm_views(request, devices)
        behaviors_map = _build_device_behaviors_map(request, devices)
        return [
            _to_device_response(
                device,
                fsm_views.get(device.ha_entity_id, []),
                behaviors_map.get(device.ha_entity_id, []),
            )
            for device in devices
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении списка устройств: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при получении списка устройств",
        ) from e


@router.get("/{device_id}", status_code=status.HTTP_200_OK)
async def get_device(request: Request, device_id: UUID) -> DeviceResponse:
    """T033: Получает информацию об устройстве с полной конфигурацией.

    Args:
        request: HTTP запрос (идентификация из middleware)
        device_id: ID устройства

    Returns:
        Информация об устройстве с конфигурацией (display_name, description, location, tags)

    Raises:
        HTTPException: 403 если нет роли viewer; 404 если устройство не найдено
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_VIEWER)

    # Состояния автоматов и последнее решение: без них страница прибора не
    # отвечает на «почему так» (спека 017, US3). Ключи решения — идентификаторы
    # автоматов устройства и его сущность.
    container = getattr(request.app.state, "container", None)
    engine = getattr(container, "fsm", None)
    fsm_views = build_all_fsm_state_views(engine, {device.ha_entity_id}) if engine else []
    decision = decision_view(engine, [view.fsm_id for view in fsm_views] + [device.ha_entity_id])

    return _to_device_response(
        device,
        fsm_views=fsm_views,
        behaviors=_device_behaviors(get_lifecycle_service(request), device.ha_entity_id),
        decision=decision,
    )


@router.get("/{device_id}/events", status_code=status.HTTP_200_OK)
async def get_device_events(
    device_id: UUID,
    request: Request,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DeviceEventResponse]:
    """T057: Получает историю событий устройства.

    Args:
        device_id: ID устройства
        request: HTTP запрос (идентификация из middleware)
        event_type: Фильтр по типу события (опционально)
        limit: Максимальное количество событий
        offset: Смещение для пагинации

    Returns:
        Список событий устройства

    Raises:
        HTTPException: 403 если нет роли viewer; 404 если устройство не найдено
    """
    device_service = get_device_service(request)
    device = await device_service.get_device(device_id)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Устройство {device_id} не найдено"
        )

    await _require_access_or_403(request, device_id, _ROLE_VIEWER)

    try:
        history = get_sync_history(request)
        if history is None:
            logger.warning(f"История операций недоступна для устройства {device_id}")
            return []

        events = await history.list_events(device_id, action=event_type, limit=limit, offset=offset)
        return [_to_event_response(event) for event in events]

    except Exception as e:
        logger.error(f"Ошибка при получении событий устройства: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка при получении событий"
        ) from e


# ============ Добавление устройств из Home Assistant ============
