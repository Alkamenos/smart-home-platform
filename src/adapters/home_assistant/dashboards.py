"""Панели Home Assistant: чтение, создание и состав (спека 018, US4).

Выделено из `HAAdapter`, чтобы транспорт и управление панелями не жили в одном
классе на две тысячи строк. Функции принимают WebSocket-клиент, а не адаптер:
им нужен только `command`.
"""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


async def find_dashboard(client: Any, url_path: str) -> dict[str, Any] | None:
    """Найти панель по пути.

    Args:
        client: WebSocket-клиент Home Assistant.
        url_path: Путь панели.

    Returns:
        Описание панели либо ``None``.
    """
    if client is None:
        return None
    answer = await client.command("lovelace/dashboards/list")
    panels = answer.get("result") if isinstance(answer, dict) else None
    for panel in panels or []:
        if isinstance(panel, dict) and panel.get("url_path") == url_path:
            return panel
    return None


async def create_dashboard(
    client: Any,
    url_path: str,
    title: str,
    icon: str = "mdi:home-automation",
) -> bool:
    """Создать панель в Home Assistant.

    Args:
        client: WebSocket-клиент.
        url_path: Путь новой панели.
        title: Название.
        icon: Значок.

    Returns:
        True, если панель создана (или уже была).
    """
    if client is None:
        return False
    answer = await client.command(
        "lovelace/dashboards/create",
        url_path=url_path,
        title=title,
        icon=icon,
        show_in_sidebar=True,
        require_admin=False,
    )
    return bool(isinstance(answer, dict) and answer.get("success"))


async def save_dashboard_config(client: Any, url_path: str, config: dict[str, Any]) -> bool:
    """Сохранить конфигурацию панели.

    Args:
        client: WebSocket-клиент.
        url_path: Путь панели.
        config: Конфигурация Lovelace.

    Returns:
        True, если конфигурация принята.
    """
    if client is None:
        return False
    answer = await client.command("lovelace/config/save", url_path=url_path, config=config)
    return bool(isinstance(answer, dict) and answer.get("success"))


async def get_dashboard_entities(client: Any) -> set[str] | None:
    """Собрать сущности, выведенные на панели.

    Args:
        client: WebSocket-клиент.

    Returns:
        Множество сущностей; ``None``, если панели прочитать не удалось.
    """
    if client is None:
        return None

    configs: list[Any] = []
    default = await client.command("lovelace/config")
    if not (isinstance(default, dict) and default.get("success")):
        logger.warning("HAAdapter: панели Home Assistant не прочитаны")
        return None
    configs.append(default.get("result"))

    listing = await client.command("lovelace/dashboards/list")
    panels = listing.get("result") if isinstance(listing, dict) else None
    for panel in panels or []:
        if not isinstance(panel, dict) or not panel.get("url_path"):
            continue
        answer = await client.command("lovelace/config", url_path=panel["url_path"])
        if isinstance(answer, dict) and answer.get("success"):
            configs.append(answer.get("result"))

    found: set[str] = set()
    for config in configs:
        _collect_entity_ids(config, found)
    return found


def _collect_entity_ids(node: Any, found: set[str]) -> None:
    """Собрать идентификаторы сущностей из описания панели.

    Args:
        node: Узел описания (словарь, список, строка).
        found: Накопитель идентификаторов.

    Returns:
        Ничего.
    """
    if isinstance(node, str):
        domain, _, rest = node.partition(".")
        if rest and domain.isidentifier() and domain.islower():
            found.add(node)
    elif isinstance(node, dict):
        for value in node.values():
            _collect_entity_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_entity_ids(value, found)
