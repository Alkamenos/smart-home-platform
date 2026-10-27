"""Действия штор: открыть и закрыть."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.actions.common import extract_device_id
from core.commands.dispatcher import CommandIntent


def _cover_intent(context: dict[str, Any], service: str, source: str) -> CommandIntent | None:
    """Собрать команду шторы.

    В данных — ничего, кроме сущности: ``cover.open_cover`` и
    ``cover.close_cover`` параметров не принимают, а лишний ключ Home Assistant
    отвергает с 400 Bad Request (research.md D23). Движением прибора платформа
    не управляет — она только просит открыть или закрыть.

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant (``open_cover`` или ``close_cover``).
        source: Источник для аудита и блокировок.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None
    logger.info(f"Создаю команду {service} для {entity_id}")
    return CommandIntent(
        device_id=entity_id,
        domain="cover",
        service=service,
        data={},
        priority=context.get("priority", 50),
        source=source,
        # Ручное положение шторы держит отдельное состояние MANUAL, а не
        # часовой локкаут (B104). Смена флагов дома — новое решение владельца:
        # она должна пройти сразу, иначе «до следующей смены флагов» означало
        # бы «через час».
        bypass_lockout=True,
    )


def cover_open(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Открыть штору.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда открытия либо ``None`` без устройства.
    """
    return _cover_intent(context, "open_cover", "cover_open")


def cover_close(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Закрыть штору.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда закрытия либо ``None`` без устройства.
    """
    return _cover_intent(context, "close_cover", "cover_close")
