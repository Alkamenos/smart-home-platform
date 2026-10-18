"""Зеркало состояний автоматов в вспомогательные элементы Home Assistant (B79).

Состояние автомата (`OFF`, `ON_MOTION`, `HEATING`, `SUPPLY`…) живёт в памяти
движка и в журнале переходов платформы. Владелец смотрит дом из Home Assistant,
и там у состояния появляется **нативная история**: помощник `input_text`
пишется при каждом переходе, а запись и график рисует сам дом.

Почему помощники, а не сенсоры автообнаружения: владелец просил именно
вспомогательные элементы, и Home Assistant 2026.10 умеет создавать их через API
(`input_text/list|create|delete`) — проверено живьём 18.10. Платформа создаёт
недостающие сама, иначе пришлось бы заводить два десятка помощников руками.

Имена помощников технические и латиницей (`fsm light.svet_nad_stolom_lighting_10`):
из имени Home Assistant собирает идентификатор сущности, и кириллица сделала бы
его непредсказуемым — на этом дашборд уже обжигался (см. B79). Латиница даёт
ровно тот идентификатор, который ждёт дашборд, — его считает `core.fsm.naming`.

Отказ дома не ломает ни переход, ни журнал: зеркало — лучшее усилие, ошибка
только в журнале (FR-009, R-06).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from loguru import logger

from core.fsm.naming import (
    HELPER_DOMAIN,
    HELPER_MAX_LENGTH,
    helper_entity_id,
    helper_name,
)


#: Значок помощника в интерфейсе дома.
HELPER_ICON = "mdi:state-machine"


class FsmHelperMirror:
    """Создавать помощников и писать в них состояние автомата.

    Args:
        send_command: Отправить команду WebSocket API помощников:
            ``(command_type, **payload) -> ответ дома``.
        publish_state: Записать значение в помощник: ``(entity_id, value) -> bool``.
        icon: Значок помощника.
    """

    def __init__(
        self,
        *,
        send_command: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        publish_state: Callable[[str, str], Awaitable[bool]] | None = None,
        icon: str = HELPER_ICON,
    ) -> None:
        self._send = send_command
        self._publish = publish_state
        self._enabled = send_command is not None and publish_state is not None
        self._icon = icon
        #: Автомат → идентификатор сущности помощника. Заполняется `ensure`.
        self._entities: dict[str, str] = {}
        self._created = 0
        self._published = 0
        self._failed = 0

    async def ensure(self, fsm_ids: Iterable[str]) -> dict[str, str]:
        """Создать недостающих помощников и вернуть карту «автомат → сущность».

        Существующие помощники ищутся по имени: идентификатор сущности в доме
        мог быть выдан иначе, и гадать о нём нельзя.

        Args:
            fsm_ids: Идентификаторы автоматов.

        Returns:
            Карта «автомат → ``input_text.…``» (пустая, если зеркало выключено
            или дом не отдал список).
        """
        if not self._enabled:
            return {}
        existing = await self._existing_by_name()
        if existing is None:
            return {}

        for fsm_id in fsm_ids:
            if fsm_id in self._entities:
                continue
            name = helper_name(fsm_id)
            found = existing.get(name)
            if found:
                self._entities[fsm_id] = f"{HELPER_DOMAIN}.{found}"
                continue
            created = await self._create(name)
            if created:
                self._entities[fsm_id] = f"{HELPER_DOMAIN}.{created}"
        return dict(self._entities)

    async def write(self, fsm_id: str, state: str | None) -> bool:
        """Записать состояние автомата в его помощника.

        Args:
            fsm_id: Идентификатор автомата.
            state: Новое состояние.

        Returns:
            True, если значение записано.
        """
        if not self._enabled or not state:
            return False
        entity = self._entities.get(fsm_id) or helper_entity_id(fsm_id)
        self._entities.setdefault(fsm_id, entity)
        return await self._set_value(entity, str(state))

    async def _existing_by_name(self) -> dict[str, str] | None:
        """Список помощников дома: имя → идентификатор.

        Returns:
            Словарь либо ``None``, если дом не ответил (тогда создавать нельзя:
            иначе на каждый старт появлялись бы дубликаты).
        """
        assert self._send is not None
        try:
            reply = await self._send("input_text/list")
        except Exception as exc:  # noqa: BLE001 — зеркало не важнее переходов
            self._failed += 1
            logger.warning(f"Зеркало автоматов: список помощников не получен: {exc}")
            return None
        if not reply.get("success"):
            self._failed += 1
            logger.warning(f"Зеркало автоматов: список помощников отвергнут: {reply.get('error')}")
            return None
        names: dict[str, str] = {}
        for item in reply.get("result") or []:
            name = item.get("name")
            helper = item.get("id")
            if name and helper:
                names[str(name)] = str(helper)
        return names

    async def _create(self, name: str) -> str | None:
        """Создать помощника.

        Args:
            name: Имя помощника.

        Returns:
            Идентификатор созданного помощника либо ``None``.
        """
        assert self._send is not None
        try:
            reply = await self._send(
                "input_text/create",
                name=name,
                initial="",
                max=HELPER_MAX_LENGTH,
                icon=self._icon,
            )
        except Exception as exc:  # noqa: BLE001 — зеркало не важнее переходов
            self._failed += 1
            logger.warning(f"Зеркало автоматов: помощник «{name}» не создан: {exc}")
            return None
        if not reply.get("success"):
            self._failed += 1
            logger.warning(f"Зеркало автоматов: помощник «{name}» отвергнут: {reply.get('error')}")
            return None
        helper = (reply.get("result") or {}).get("id")
        if not helper:
            self._failed += 1
            logger.warning(f"Зеркало автоматов: дом не назвал идентификатор «{name}»")
            return None
        self._created += 1
        logger.info(f"Зеркало автоматов: создан помощник {HELPER_DOMAIN}.{helper}")
        return str(helper)

    async def _set_value(self, entity_id: str, value: str) -> bool:
        """Записать значение в помощник.

        Args:
            entity_id: Идентификатор сущности помощника.
            value: Значение.

        Returns:
            True, если записано.
        """
        assert self._publish is not None
        try:
            ok = await self._publish(entity_id, value)
        except Exception as exc:  # noqa: BLE001 — зеркало не важнее переходов
            self._failed += 1
            logger.warning(f"Зеркало автоматов: {entity_id} не записан: {exc}")
            return False
        if ok:
            self._published += 1
        else:
            self._failed += 1
            logger.warning(f"Зеркало автоматов: дом отверг запись {entity_id}")
        return bool(ok)

    def describe(self) -> dict[str, Any]:
        """Описание зеркала для журнала и готовности.

        Returns:
            Словарь: включено ли, сколько помощников известно, создано, записано
            и сколько отказов.
        """
        return {
            "enabled": self._enabled,
            "helpers": len(self._entities),
            "created": self._created,
            "published": self._published,
            "failed": self._failed,
        }
