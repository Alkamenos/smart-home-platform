"""Общие помощники действий: устройство из контекста и освобождение захвата."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger


def extract_device_id(context: dict[str, Any]) -> str | None:
    """
    Extract device ID from context using fallback chain.

    Priority order:
    1. target_device_id (from FSM definition)
    2. entity_id (from event context)
    3. device_id (legacy fallback)

    Args:
        context: Context dictionary containing device identifiers.

    Returns:
        Device ID string or None if not found.
    """
    return context.get("target_device_id") or context.get("entity_id") or context.get("device_id")


def release_device(state: Any, context: dict) -> None:
    """
    Освобождает устройство от захвата FSM.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing dispatcher, target_device_id, and source.
    """
    dispatcher = context.get("dispatcher")
    entity_id = extract_device_id(context)
    source = context.get("source")

    if dispatcher and entity_id and source:
        dispatcher.release(entity_id, source)
        logger.info(f"Released device {entity_id} from {source}")
    else:
        logger.warning(
            f"release_device: Missing dispatcher={dispatcher}, "
            f"entity_id={entity_id}, or source={source}"
        )
