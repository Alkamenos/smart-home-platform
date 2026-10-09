"""
T008: Снимок состояний дома с кэшем.

Читает состояния всех сущностей из Home Assistant одним запросом через
WebSocket клиент адаптера. Кэширует результат на 5 секунд для снижения
нагрузки и обеспечения согласованности в пределах одного цикла отрисовки
интерфейса.

# Copyright 2026 Leonid Artemev
# SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class DeviceState:
    """Состояние одного устройства или датчика в Home Assistant.

    Attributes:
        entity_id: Идентификатор в Home Assistant (light.kitchen, sensor.temp_room1).
        state: Текущее значение ('on', 'off', '21.5', 'unavailable', 'unknown').
        unit_of_measurement: Единица измерения из атрибутов (°C, %, None).
        available: Доступно ли устройство (не 'unavailable' и не 'unknown').
        attributes: Полные атрибуты из HA (для будущих расширений).
    """

    entity_id: str
    state: str
    unit_of_measurement: str | None = None
    available: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ha_state(cls, entity_data: dict[str, Any]) -> DeviceState:
        """Построить из ответа HA /api/states.

        Args:
            entity_data: Одна запись из HA (содержит state, attributes и т.д.).

        Returns:
            DeviceState с разобранными полями.
        """
        state_value = entity_data.get("state", "unknown")
        attributes = entity_data.get("attributes", {})
        unit = attributes.get("unit_of_measurement")

        # Недоступное состояние отличается от выключенного
        available = state_value not in ("unavailable", "unknown")

        return cls(
            entity_id=entity_data.get("entity_id", "unknown"),
            state=state_value,
            unit_of_measurement=unit,
            available=available,
            attributes=attributes,
        )


@dataclass
class Snapshot:
    """Снимок состояний дома с метаданными.

    Attributes:
        states: Словарь {entity_id → DeviceState}.
        at: Время снятия снимка (Unix timestamp).
        reachable: Доступен ли Home Assistant при снятии снимка.
        last_successful_at: Время последнего успешного снимка (для меток «нет связи»).
    """

    states: dict[str, DeviceState]
    at: float
    reachable: bool = True
    last_successful_at: float = 0.0


class StateSnapshot:
    """Управление снимками состояний дома с кэшем (T008, FR-001).

    Читает состояния из HA один раз в кэш_время, повторные запросы в пределах
    кэша возвращают тот же снимок. При недоступности HA возвращает последний
    успешный снимок с пометкой reachable=false.

    Использует WebSocket клиент адаптера (ha_adapter._ws_client.get_states()),
    а не REST, потому что WebSocket уже открыт и в цикле, а REST требовал бы
    отдельного подключения и был бы медленнее.
    """

    def __init__(self, ha_adapter: Any, cache_ttl_sec: float = 5.0) -> None:
        """Инициализировать снимок состояний.

        Args:
            ha_adapter: Адаптер Home Assistant с методом get_states() через WebSocket.
            cache_ttl_sec: Время кэширования в секундах (по умолчанию 5).
        """
        self._adapter = ha_adapter
        self._cache_ttl = cache_ttl_sec
        self._cached_snapshot: Snapshot | None = None
        self._cache_time: float = 0.0

    async def read(self) -> Snapshot:
        """Прочитать состояния дома или вернуть кэш.

        Если кэш свежий, возвращает его. Если кэш устарел или пуст, запрашивает
        состояния из HA и кэширует результат. При ошибке HA возвращает последний
        успешный снимок с reachable=false.

        Returns:
            Snapshot с состояниями и статусом доступности.

        Raises:
            ValueError: Если адаптер не инициализирован или HA вернул неверный формат.
        """
        now = time.time()

        # Кэш свежий?
        if self._cached_snapshot is not None and (now - self._cache_time) < self._cache_ttl:
            logger.debug(
                f"StateSnapshot: cache hit (age {now - self._cache_time:.1f}s, "
                f"ttl {self._cache_ttl}s, states {len(self._cached_snapshot.states)})"
            )
            return self._cached_snapshot

        # Кэш устарел, запрашиваем состояния
        logger.debug("StateSnapshot: cache miss or expired, reading from HA...")
        try:
            ha_states = await self._get_states_from_adapter()
            if ha_states is None:
                # Адаптер недоступен или вернул пусто
                logger.warning("StateSnapshot: HA returned None, using last successful snapshot")
                return self._fallback_snapshot(now)

            # Разбираем состояния
            states_dict: dict[str, DeviceState] = {}
            for entity_data in ha_states:
                try:
                    device_state = DeviceState.from_ha_state(entity_data)
                    states_dict[device_state.entity_id] = device_state
                except (KeyError, TypeError) as e:
                    logger.warning(f"StateSnapshot: failed to parse entity {entity_data}: {e}")
                    continue

            # Кэшируем успешный снимок
            snapshot = Snapshot(
                states=states_dict,
                at=now,
                reachable=True,
                last_successful_at=now,
            )
            self._cached_snapshot = snapshot
            self._cache_time = now

            logger.info(
                f"StateSnapshot: read {len(states_dict)} entities from HA, "
                f"caching for {self._cache_ttl}s"
            )
            return snapshot

        except Exception as e:
            logger.error(f"StateSnapshot: error reading from HA: {e}")
            return self._fallback_snapshot(now)

    async def _get_states_from_adapter(self) -> list[dict[str, Any]] | None:
        """Получить состояния через адаптер.

        Returns:
            Список состояний из HA или None при ошибке.
        """
        try:
            # Адаптер должен иметь метод get_states() через WebSocket клиент
            ws_client = getattr(self._adapter, "_ws_client", None)
            if ws_client is None:
                logger.warning("StateSnapshot: HA WebSocket client not available")
                return None

            states = await ws_client.get_states()
            return states if isinstance(states, list) else None
        except Exception as e:
            logger.error(f"StateSnapshot: failed to get states from adapter: {e}")
            return None

    def _fallback_snapshot(self, now: float) -> Snapshot:
        """Вернуть последний успешный снимок или пустой при недоступности HA.

        Args:
            now: Текущее время (для поля 'at').

        Returns:
            Snapshot с reachable=false и последними известными состояниями.
        """
        if self._cached_snapshot is not None:
            return Snapshot(
                states=self._cached_snapshot.states,
                at=now,
                reachable=False,
                last_successful_at=self._cached_snapshot.last_successful_at,
            )

        # Снимков ещё не было — пустой результат
        return Snapshot(states={}, at=now, reachable=False, last_successful_at=0.0)
