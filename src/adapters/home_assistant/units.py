"""Units and setpoint synchronization for the Home Assistant adapter.

Extracted from HAAdapter (spec 018, US4): measurement units and thermostat
setpoint mirroring are a separate responsibility from transport.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from loguru import logger

from adapters.ha_websocket import _as_float as _as_float, _is_number as _is_number


class UnitsMixin:
    """Unit memory and thermostat/setpoint synchronization."""

    if TYPE_CHECKING:
        _session: Any
        _token: str | None
        _ws_url: str | None
        _entity_units: dict[str, str]
        climate_entities: dict[str, str]

        async def get_attribute(self, entity_id: str, attribute: str) -> Any: ...

        async def get_state(self, entity_id: str) -> str | None: ...

        async def call_service(
            self,
            domain: str,
            service: str,
            entity_id: str = "",
            data: dict[str, Any] | None = None,
            trace_id: str | None = None,
        ) -> Any: ...

    async def refresh_units(self, entity_ids: Iterable[str]) -> int:
        """Запомнить единицы измерения сущностей наблюдения (спека 016).

        Отдельно от ``refresh_entity_units``: там речь о таймерах обогрева и
        своё предупреждение. Здесь — единицы датчиков (температура, влажность,
        почва): без них снимок локации отдаёт «22.4» без «°C», и значение нельзя
        ни сравнить, ни построить по нему график.

        Args:
            entity_ids: Сущности, единицу которых нужно знать.

        Returns:
            Сколько единиц удалось запомнить.
        """
        learned = 0
        for entity_id in sorted({entity for entity in entity_ids if entity}):
            unit = await self.get_attribute(entity_id, "unit_of_measurement")
            if isinstance(unit, str) and unit.strip():
                self.remember_entity_unit(entity_id, unit)
                learned += 1
        if learned:
            logger.info(f"HAAdapter: единицы измерения запомнены для {learned} сущностей")
        return learned

    async def sync_setpoint(self, entity_id: str, value: str, own_action: bool) -> None:
        """Синхронизировать термостат и уставку дома в обоих направлениях.

        Требование владельца 2026-10-12: изменение цели термостата меняет
        уставку, изменение уставки пишется в термостат. Источник истины —
        последнее изменённое; вторая сторона — зеркало.

        Петля обрывается дважды: наши команды возвращаются из Home Assistant
        с тем же ``context.id`` (``own_action``), а равные значения не порождают
        команду вовсе.

        Args:
            entity_id: Сущность, у которой изменилось значение.
            value: Новое значение (для климата — режим, цель читается из
                атрибута).
            own_action: Событие вызвано собственной командой платформы.

        Returns:
            Ничего. Ошибки логируются и не прерывают обработку события.
        """
        if own_action:
            return

        thermostat = self.climate_entities.get("thermostat")
        setpoint_entity = self.climate_entities.get("setpoint")
        if not thermostat or not setpoint_entity:
            # Термостат не задан в комнате — синхронизировать не с кем.
            return

        if entity_id == thermostat:
            raw = (
                value if _is_number(value) else await self.get_attribute(thermostat, "temperature")
            )
            target = _as_float(raw)
            if target is None:
                logger.warning(f"sync_setpoint: цель термостата {raw!r} не число")
                return
            current = _as_float(await self.get_state(setpoint_entity))
            if current is not None and abs(current - target) < 0.05:
                return
            logger.warning(
                f"Термостат {thermostat} задал уставку {target}: "
                f"{setpoint_entity} зеркалируется (было {current})"
            )
            await self.call_service("input_number", "set_value", setpoint_entity, {"value": target})
            return

        if entity_id == setpoint_entity:
            target = _as_float(value)
            if target is None:
                logger.warning(f"sync_setpoint: уставка {value!r} не число")
                return
            current = _as_float(await self.get_attribute(thermostat, "temperature"))
            if current is not None and abs(current - target) < 0.05:
                return
            logger.warning(
                f"Уставка {setpoint_entity} = {target}: зеркалируется в цель "
                f"термостата {thermostat} (была {current})"
            )
            await self.call_service(
                "climate", "set_temperature", thermostat, {"temperature": target}
            )

    @staticmethod
    def setpoint_from_event(entity_id: str, payload: dict[str, Any]) -> str | None:
        """Новая уставка из события: атрибут цели у климата, состояние у остальных.

        У `climate.*` цель живёт в атрибуте `temperature`, а состояние климата —
        это режим (`heat`/`off`). Подставить состояние в уставку значило бы
        положить строку `heat` туда, где условие ждёт число.

        Args:
            entity_id: Сущность события.
            payload: Конверт события (`event.data`).

        Returns:
            Новая уставка либо ``None``, если прочитать нельзя.
        """
        if entity_id.startswith("climate."):
            raw = payload.get("new_state")
            if isinstance(raw, dict):
                attributes = raw.get("attributes")
                if isinstance(attributes, dict):
                    target = attributes.get("temperature")
                    return str(target) if target is not None else None
            return None
        raw = payload.get("new_state")
        state = raw.get("state") if isinstance(raw, dict) else raw
        return str(state) if state is not None else None

    def remember_entity_unit(self, entity_id: str, unit: Any) -> None:
        """Запомнить единицу измерения сущности, прочитанную у устройства.

        Args:
            entity_id: Сущность Home Assistant.
            unit: Единица измерения из атрибутов состояния (``unit_of_measurement``).

        Returns:
            Ничего.
        """
        if isinstance(unit, str) and unit.strip():
            self._entity_units[entity_id] = unit.strip()

    def get_entity_unit(self, entity_id: str) -> str | None:
        """Единица измерения сущности, если она была прочитана.

        Args:
            entity_id: Сущность Home Assistant.

        Returns:
            Единица измерения либо ``None``, если сущность не наблюдалась или
            устройство единицу не назвало.
        """
        return self._entity_units.get(entity_id)

    async def refresh_entity_units(self, entity_ids: Iterable[str]) -> int:
        """Прочитать единицы измерения таймеров и запомнить их.

        Единица нужна, чтобы команда обогревателю попала в ту величину, которой
        измеряет устройство. Раньше платформа отправляла минуты в таймер,
        измеряемый в секундах: Home Assistant принимала значение, обогреватель
        включался и гас через 15 секунд, а автомат честно отрабатывал свой
        таймер — обогрев не работал сутки без единого признака.

        Args:
            entity_ids: Сущности, единицу которых нужно знать (таймеры).

        Returns:
            Сколько сущностей удалось прочитать.
        """
        if self._session is None or not self._token:
            return 0

        http_url = cast(str, self._ws_url)
        base = http_url.replace("wss://", "https://").replace("ws://", "http://")
        base = base.split("/api/websocket")[0].rstrip("/")
        learned = 0
        for entity_id in entity_ids:
            try:
                async with self._session.get(
                    f"{base}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"HAAdapter: единица измерения {entity_id} не прочитана "
                            f"(HTTP {response.status}) — таймер получит длительность "
                            "в минутах, а если он в секундах, обогреватель выключится "
                            "почти сразу"
                        )
                        continue
                    payload = await response.json()
            except (TimeoutError, aiohttp.ClientError, ValueError) as error:
                logger.warning(f"HAAdapter: единица измерения {entity_id} не прочитана: {error}")
                continue

            attributes = payload.get("attributes") or {}
            unit = attributes.get("unit_of_measurement")
            if isinstance(unit, str) and unit.strip():
                self.remember_entity_unit(entity_id, unit)
                learned += 1
            else:
                logger.warning(
                    f"HAAdapter: {entity_id} не называет единицу измерения — приняты минуты"
                )

        if learned:
            # WARNING по той же причине, что и у вызова: info от адаптера не
            # виден, а молчание здесь выглядело бы как «единицы не нужны».
            logger.warning(f"HAAdapter: единицы измерения прочитаны для {learned} сущностей")
        return learned
