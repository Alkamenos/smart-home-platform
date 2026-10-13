"""Применение манифеста к работающей платформе (спека 017, US5, FR-027).

Правка манифеста обязана применяться без перезапуска: иначе сохранённый файл
и работающая платформа расходятся, и новое устройство «не появляется».
Здесь собрано то, что нужно перечитать после записи: сам манифест, состав
автоматов и карта маршрутизации событий.

Логика вынесена из прежнего HTML-маршрута перечитывания: страницы больше нет,
но поведение нужно — оно переехало в правку манифеста.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from loguru import logger


def apply_manifest_to_runtime(
    store: Any,
    container: Any,
    lifecycle_service: Any = None,
) -> None:
    """Перечитать манифест и перестроить рантайм под него.

    Args:
        store: Хранилище манифеста.
        container: Контейнер платформы (может отсутствовать).
        lifecycle_service: Сервис жизненного цикла устройств либо ``None``.

    Raises:
        ValidationError: Если файл манифеста не разбирается (цель не меняется).
    """
    if container is None or getattr(container, "manifest", None) is None:
        return

    store.reload_into(container.manifest)

    factory = container.factory
    definitions = list(factory.create_from_manifest(container.manifest))
    wanted = {definition.entity_id for definition in definitions}

    # Снять автоматы, которых больше нет, и завести новые. Состояния
    # сохраняются: лампа, включённая по движению, не должна «забывать» об этом.
    for entity_id in list(container.fsm.get_all_states()):
        if entity_id not in wanted:
            container.fsm.unregister(entity_id)
    for definition in definitions:
        container.fsm.register_definition(definition, restore_state=True)

    factory._template_cache.clear()

    # Карта маршрутизации строится из манифеста, поэтому перечитывание обязано её
    # перестроить: иначе датчик новой комнаты молчал бы.
    if lifecycle_service is not None:
        lifecycle_service._rebuild_event_routing()
    elif container.event_router is not None:
        container.event_router._build_mapping()

    # Наблюдение за локациями строится один раз при старте: без перестройки
    # новые привязки датчиков не появятся в снимке до перезапуска, то есть
    # «сохранено, но не применено» (спека 017, FR-027).
    service = getattr(container, "location_state", None)
    rebuild = getattr(service, "rebuild", None)
    if callable(rebuild):
        rebuild()

    logger.info(
        f"Манифест применён: комнат {len(container.manifest.rooms)}, автоматов {len(wanted)}"
    )


async def prime_location_state(container: Any) -> None:
    """Прочитать текущие значения датчиков после перестройки наблюдения.

    Событие изменения придёт не для каждого датчика (контакт окна не менялся) —
    без первичного чтения новый датчик показывался бы пустым до первого события.

    Args:
        container: Контейнер платформы.
    """
    service = getattr(container, "location_state", None)
    prime = getattr(service, "prime", None)
    if not callable(prime):
        return
    try:
        await prime()
    except Exception as exc:  # noqa: BLE001 — чтение не должно ломать применение
        logger.warning(f"Наблюдение за локациями: первичное чтение не удалось: {exc}")
