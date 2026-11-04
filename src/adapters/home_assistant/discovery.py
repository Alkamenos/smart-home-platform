"""Discovery and registry reads for the Home Assistant adapter.

Extracted from HAAdapter (spec 018, US4): reading all states and the entity
registry is a separate responsibility from transport and commands.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


logger = logging.getLogger(__name__)


class DiscoveryMixin:
    """Read Home Assistant states and the entity registry."""

    if TYPE_CHECKING:
        _ws_client: Any

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Прочитать состояния всех сущностей одним запросом.

        Нужно сверке состояний при старте (B62): состояние устройства —
        следствие источника истины, а не снимок из хранилища. Читается через
        WebSocket (`get_states`), потому что REST-перебор 1495 сущностей был бы
        1495 запросами.

        Returns:
            Список состояний Home Assistant; пустой, если связи нет.
        """
        client = self._ws_client
        if client is None:
            return []
        try:
            states = await client.get_states()
        except Exception as exc:  # noqa: BLE001 — сверка не должна ронять старт
            logger.warning(f"HAAdapter: состояния сущностей не прочитаны: {exc}")
            return []
        if not isinstance(states, list):
            return []
        return [state for state in states if isinstance(state, dict)]

    async def get_entity_registry(self) -> list[dict[str, Any]]:
        """Прочитать реестр сущностей Home Assistant (BACKLOG B77).

        Реестр отвечает на вопрос, которого не видно по состояниям: **откуда**
        сущность взялась. У созданной через интерфейс дома есть запись
        конфигурации, у описанной в YAML — нет, и удалить их можно по-разному:
        первую — через дом, вторую — только правкой YAML на самом доме.

        Returns:
            Записи реестра; пусто, если дом не ответил.
        """
        client = self._ws_client
        if client is None:
            return []
        try:
            answer = await client.command("config/entity_registry/list")
        except Exception as exc:  # noqa: BLE001 — чистка не должна ронять страницу
            logger.warning(f"HAAdapter: реестр сущностей не прочитан: {exc}")
            return []
        if not isinstance(answer, dict) or not answer.get("success"):
            # Молчаливый пустой ответ уже один раз спрятал дефект (ответ реестра
            # больше мегабайта не доходил): отказ обязан быть виден в журнале.
            logger.warning(f"HAAdapter: реестр сущностей не прочитан: {answer}")
            return []
        result = answer.get("result")
        return [item for item in result or [] if isinstance(item, dict)]
