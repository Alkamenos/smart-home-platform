"""Проблемы дома в Home Assistant через MQTT-автообнаружение (BACKLOG B79).

Дашборд в доме показывает комнаты и приборы, но «что требует внимания» жило
только в веб-интерфейсе платформы. Владелец смотрит дом с телефона, поэтому
обход дома публикует свою сводку как сущность Home Assistant:

* ``sensor.platform_problems`` — сколько проблем сейчас;
* атрибуты — что именно и где.

Почему автообнаружение, а не «создать сущность»: платформа не умеет создавать
сущности в Home Assistant, она может только писать в существующие. Объявление
(``homeassistant/sensor/.../config``) создаёт сущность сам дом (тот же приём, что
у зеркала локаций, спека 016).

Публикация идёт через адаптер (``core`` не импортирует ``adapters``,
`.ai/04_RULES.md`) и с ``retain``: после перезапуска Home Assistant сущность
восстанавливается, не дожидаясь нового обхода. Отказ публикации не ломает обход
(FR-009): он считается и называется в журнале.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger


#: Префикс топиков значений (тот же, что у зеркала локаций).
DEFAULT_PREFIX = "behavioral"

#: Префикс автообнаружения Home Assistant.
DISCOVERY_PREFIX = "homeassistant"

#: Как называется платформа в Home Assistant как устройство.
MANUFACTURER = "Smart Home Platform"

#: Идентификатор сущности в Home Assistant.
#:
#: Почему не «просто object_id»: Home Assistant 2026.10 **игнорирует**
#: `object_id` в автообнаружении (проверено живьём 18.10: три пробных
#: объявления дали ``sensor.a``/``sensor.b``/``sensor.c`` вместо заданных имён).
#: Идентификатор собирается из имени устройства и имени сущности, кириллица
#: транслитерируется: «Платформа» + «Проблемы в доме» → ``platforma_problemy_v_dome``.
#: Пара имён закреплена проверкой, и на неё ссылается генератор дашборда: менять
#: одно без другого нельзя.
PLATFORM_PROBLEMS_ENTITY_ID = "sensor.platforma_problemy_v_dome"

#: Подпись сущности для владельца.
PLATFORM_PROBLEMS_NAME = "Проблемы в доме"


class PlatformMirror:
    """Публиковать сводку обхода дома в Home Assistant.

    Args:
        publish: Как опубликовать топик: ``(topic, payload, retain) -> bool``.
            Обычно адаптер: ``mqtt.publish``.
        prefix: Префикс топиков значений.
        discovery_prefix: Префикс автообнаружения Home Assistant.
        enabled: Публиковать ли вообще (дом без MQTT выключает зеркало).
    """

    def __init__(
        self,
        *,
        publish: Callable[[str, str, bool], Awaitable[bool]] | None = None,
        prefix: str = DEFAULT_PREFIX,
        discovery_prefix: str = DISCOVERY_PREFIX,
        enabled: bool = True,
    ) -> None:
        self._publish = publish
        self._prefix = prefix.strip("/") or DEFAULT_PREFIX
        self._discovery = discovery_prefix.strip("/") or DISCOVERY_PREFIX
        self._enabled = enabled and publish is not None
        #: Объявление публикуется один раз за процесс: повтор стоит вызова и
        #: ничего не меняет — Home Assistant помнит конфигурацию по unique_id.
        self._announced = False
        self._published = 0
        self._failed = 0

    async def publish_report(self, report: dict[str, Any] | None) -> bool:
        """Опубликовать сводку обхода: число проблем и их список.

        Args:
            report: Снимок обхода дома (``problems``, ``generated_at``,
                ``sensor_count``) либо ``None``, если обход ещё не проходил.

        Returns:
            True, если всё опубликовано (или зеркало выключено).
        """
        if not self._enabled or not report:
            return False

        ok = await self._announce()
        problems = list(report.get("problems") or [])
        ok = await self._send(f"{self._prefix}/platform/problems/state", str(len(problems))) and ok
        attributes = {
            "generated_at": report.get("generated_at"),
            "sensor_count": report.get("sensor_count", 0),
            "problems": problems,
            # Реестр показаний (`areas`) намеренно не публикуется: это килобайты
            # на каждое обновление, а карточке нужен только список проблем.
        }
        ok = (
            await self._send(
                f"{self._prefix}/platform/problems/attributes",
                json.dumps(attributes, ensure_ascii=False),
            )
            and ok
        )
        return ok

    async def _announce(self) -> bool:
        """Объявить сущность в Home Assistant (один раз за процесс).

        Returns:
            True, если объявление принято (или уже было).
        """
        if self._announced:
            return True
        device = {
            "identifiers": [f"{self._prefix}_platform"],
            "name": "Платформа",
            "manufacturer": MANUFACTURER,
            "model": "platform",
        }
        config = {
            "name": PLATFORM_PROBLEMS_NAME,
            "has_entity_name": True,
            # `object_id` Home Assistant игнорирует — идентификатор собирается из
            # пары «устройство + сущность» (см. PLATFORM_PROBLEMS_ENTITY_ID).
            "unique_id": f"{self._prefix}_platform_problems",
            "state_topic": f"{self._prefix}/platform/problems/state",
            "json_attributes_topic": f"{self._prefix}/platform/problems/attributes",
            "unit_of_measurement": "шт.",
            "icon": "mdi:home-alert",
            "device": device,
        }
        ok = await self._send(
            f"{self._discovery}/sensor/{self._prefix}_platform_problems/config",
            json.dumps(config, ensure_ascii=False),
        )
        if ok:
            self._announced = True
        return ok

    async def _send(self, topic: str, payload: str) -> bool:
        """Опубликовать топик, не роняя обход при отказе (FR-009).

        Args:
            topic: Топик MQTT.
            payload: Полезная нагрузка.

        Returns:
            True, если опубликовано.
        """
        assert self._publish is not None  # проверено в __init__
        try:
            ok = await self._publish(topic, payload, True)
        except Exception as exc:  # noqa: BLE001 — отказ зеркала не ломает снимок
            self._failed += 1
            logger.warning(f"Зеркало проблем: публикация {topic} не удалась: {exc}")
            return False
        if ok:
            self._published += 1
        else:
            self._failed += 1
            logger.warning(f"Зеркало проблем: публикация {topic} отвергнута Home Assistant")
        return bool(ok)

    def describe(self) -> dict[str, Any]:
        """Описание зеркала для журнала и готовности.

        Returns:
            Словарь: включено ли, префикс, сколько опубликовано и сколько отказов.
        """
        return {
            "enabled": self._enabled,
            "prefix": self._prefix,
            "published": self._published,
            "failed": self._failed,
        }
