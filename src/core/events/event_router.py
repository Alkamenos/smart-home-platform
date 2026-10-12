"""Event Router for Smart Home Platform.

Routes sensor events to FSMs via room context.
Same sensor entity can trigger events in multiple rooms.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.fsm.engine import FSMEngine
from core.models.manifest import Manifest


def _as_measurement(value: str | Any) -> Any:
    """Привести показание датчика к числу, если это возможно.

    Числом — чтобы условие сравнивало числа, а не строки. Строкой — чтобы
    нечитаемое значение осталось нечитаемым: молчаливое превращение «unavailable»
    в ноль выдало бы заведомо ложное решение за честное.

    Args:
        value: Новое состояние датчика, как его прислал Home Assistant.

    Returns:
        Число, если значение приводится, иначе исходное значение.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def collect_subscribed_entities(manifest: Any) -> list[str]:
    """Собрать сущности, на которые платформе нужны события.

    Список идёт в Home Assistant как фильтр подписки: без него сервер присылает
    все сущности дома, и платформа разбирает и отбивает каждое событие той,
    которая в манифесте не описана. В бою это 1502 сущности против 6 описанных.

    Берутся и устройства комнат, и их датчики: датчик комнаты без устройств тоже
    нужен, по нему приходят события движения.

    Args:
        manifest: Манифест платформы.

    Returns:
        Список `entity_id` без повторов, в исходном порядке.
    """
    entities: list[str] = []
    seen: set[str] = set()

    for room in getattr(manifest, "rooms", []) or []:
        candidates: list[Any] = [
            *(room.sensors or {}).values(),
            *(getattr(device, "id", None) for device in (room.devices or [])),
        ]
        for entity_id in candidates:
            if entity_id and entity_id not in seen:
                seen.add(entity_id)
                entities.append(entity_id)

    return entities


class EventRouter:
    """Routes state change events from sensors to registered FSMs.

    Routing logic:
    - Each room has sensors and devices
    - Sensor event triggers FSMs for ALL devices in that room
    - Same sensor in multiple rooms triggers FSMs in all those rooms
    """

    SENSOR_EVENT_MAP: dict[str, list[str]] = {
        "motion": ["motion_detected", "motion_cleared"],
        "temperature": ["temperature_changed"],
        "humidity": ["humidity_changed"],
        "lux": ["brightness_changed"],
        "contact": ["opened", "closed"],
    }

    def __init__(self, manifest: Manifest, engine: FSMEngine) -> None:
        self._manifest = manifest
        self._engine = engine
        self._sensor_to_fsms: dict[str, list[tuple[str, str]]] = {}
        # Роль датчика («humidity», «motion») по паре «датчик → автомат», а не по
        # сущности: один физический датчик может быть источником для двух комнат
        # под разными именами (например, движение гостиной плюс влажность для
        # вентилятора кабинета). Раньше роль запоминалась один раз на сущность
        # через `setdefault`, и вторая комната получала маршрут без значения —
        # условие читало ключ, которого в контексте не было.
        self._sensor_roles: dict[tuple[str, str], str] = {}
        # Комната автомата и климат-автоматы комнаты: по ним в контекст события
        # кладётся признак «обогрев работает» (`heating_active`). Признак
        # **диагностический**: с 2026-10-12 (research.md D22, FR-055) ни одно
        # условие вентиляции его не читает — право вентиляции определяет уставка
        # (FR-049). В журнале решения он остаётся ответом на утренний вопрос
        # «шёл ли обогрев, когда платформа включала приток».
        self._fsm_to_room: dict[str, str] = {}
        self._room_climate_fsms: dict[str, list[str]] = {}
        self._build_mapping()

    def _build_mapping(self) -> None:
        """Build sensor-to-FSM mapping from room structure."""
        self._fsm_to_room.clear()
        self._room_climate_fsms.clear()
        for room in self._manifest.rooms:
            # Collect all FSM entity IDs for devices in this room
            room_fsm_ids: list[str] = []
            climate_fsm_ids: list[str] = []
            for device in room.devices:
                device_fsms = self._engine.get_entities_by_device(device.id)
                room_fsm_ids.extend(device_fsms)
                for fsm_id in device_fsms:
                    self._fsm_to_room[fsm_id] = room.id
                if getattr(device, "type", None) == "climate":
                    climate_fsm_ids.extend(device_fsms)
            self._room_climate_fsms[room.id] = climate_fsm_ids

            if not room_fsm_ids:
                continue

            # Each sensor in room routes to all devices in that room
            for sensor_type, sensor_id in room.sensors.items():
                events = self.SENSOR_EVENT_MAP.get(sensor_type, [])
                if not events:
                    logger.warning(f"Unknown sensor type '{sensor_type}' in room '{room.id}'")
                    continue

                # Роль датчика запоминается отдельно от маршрута: по ней
                # значение кладётся в контекст перехода под тем именем, которое
                # читает условие. Без этого условие влажности читало ключ,
                # которого в контексте нет, и вентиляция не срабатывала никогда.
                #
                # Роль — свойство пары «датчик → автомат»: у каждой комнаты своя
                # роль для своего автомата, даже если сущность датчика общая.
                for event_name in events:
                    # Событие идёт только тем автоматам, которые его
                    # слушают. В комнате с датчиком движения и датчиком
                    # температуры автоматов два, и раньше оба получали оба
                    # события: автомат климата отвечал на движение
                    # `no_transition`, и в журнале это читалось как «свет
                    # отказал», хотя свет тут ни при чём (FR-032).
                    listeners: set[str] | None = None
                    if hasattr(type(self._engine), "entities_with_trigger"):
                        listeners = set(self._engine.entities_with_trigger(event_name))
                    for fsm_id in room_fsm_ids:
                        if listeners is not None and fsm_id not in listeners:
                            continue
                        self._add_mapping(sensor_id, fsm_id, event_name)
                        self._sensor_roles[(sensor_id, fsm_id)] = sensor_type

        logger.info(f"EventRouter built mapping for {len(self._sensor_to_fsms)} sensors")

    def _add_mapping(self, sensor_id: str, fsm_entity_id: str, event_name: str) -> None:
        """Add a mapping entry."""
        if sensor_id not in self._sensor_to_fsms:
            self._sensor_to_fsms[sensor_id] = []
        entry = (fsm_entity_id, event_name)
        if entry not in self._sensor_to_fsms[sensor_id]:
            self._sensor_to_fsms[sensor_id].append(entry)

    def rebuild(self, manifest: Manifest | None = None) -> None:
        """Перестроить карту «датчик → автоматика» с нуля.

        Нужен при изменении состава устройств во время работы системы: маппинг
        строится из манифеста и состояния движка, поэтому без перестроения
        новое устройство не получало бы событий, а записи удалённых устройств
        оставались бы навсегда (spec 006, FR-015).

        Args:
            manifest: Актуальный манифест. Если не передан, используется текущий.
        """
        if manifest is not None:
            self._manifest = manifest

        self._sensor_to_fsms.clear()
        self._sensor_roles.clear()
        self._fsm_to_room.clear()
        self._room_climate_fsms.clear()
        self._build_mapping()

    def get_mapping(self, sensor_id: str) -> list[tuple[str, str]]:
        """Get FSM mappings for a sensor."""
        return list(self._sensor_to_fsms.get(sensor_id, []))

    def get_mapping_for_sensor(self, sensor_id: str) -> list[tuple[str, str]]:
        """Get FSM mappings for a sensor (alias for get_mapping)."""
        return self.get_mapping(sensor_id)

    def _room_heating_active(self, fsm_entity_id: str) -> bool | None:
        """Работает ли обогрев в комнате автомата.

        Признак берётся из состояний климат-автоматов комнаты
        (``HEATING``). ``None`` — в комнате нет климат-автомата или движок не
        отдаёт состояния: признак неизвестен, и в журнал он тогда не попадает.
        На решения вентиляции признак не влияет (FR-055) — он диагностический.

        Args:
            fsm_entity_id: Автомат, которому адресовано событие.

        Returns:
            True — где-то в комнате работает обогрев; False — не работает;
            None — узнать не удалось.
        """
        room_id = self._fsm_to_room.get(fsm_entity_id)
        if room_id is None:
            return None
        climate_fsms = self._room_climate_fsms.get(room_id) or []
        if not climate_fsms:
            return None
        get_state = getattr(self._engine, "get_state", None)
        if get_state is None:
            return None
        for climate_fsm in climate_fsms:
            state = get_state(climate_fsm)
            if state is not None and getattr(state, "current_state", None) == "HEATING":
                return True
        return False

    async def route_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Route a state change event to all registered FSMs."""
        if context is None:
            context = {}

        mappings = self._sensor_to_fsms.get(entity_id, [])
        if not mappings:
            logger.debug(f"No FSM mappings found for sensor {entity_id}")
            return

        for fsm_entity_id, event_name in mappings:
            # Filter events based on state
            if event_name == "motion_detected" and new_state != "on":
                continue
            if event_name == "motion_cleared" and new_state != "off":
                continue

            external_ctx = {
                **context,
                "entity_id": entity_id,
                "new_state": new_state,
                "old_state": old_state,
            }

            # Признак «обогрев работает» в комнате автомата. Он
            # **диагностический**: правило «вентиляция при работающем обогреве
            # выключается» отменено 2026-10-12 (research.md D22, FR-055) — его
            # заменило правило по уставке (FR-049), а признак остаётся в журнале
            # ответом на вопрос «шёл ли обогрев». Считается по состояниям
            # климат-автоматов той же комнаты, а не по новой сущности в Home
            # Assistant: два источника истины разошлись бы, и признак остался бы
            # неизвестным.
            heating = self._room_heating_active(fsm_entity_id)
            if heating is not None:
                external_ctx["heating_active"] = heating

            # Измеримое значение датчика едет в контексте под именем его роли —
            # тем самым, которое читает условие перехода. Раньше сюда попадали
            # только имена состояний, и условие по влажности читало ключ, которого
            # в контексте не было никогда.
            #
            # Значение приводится к числу, когда это возможно, иначе остаётся
            # строкой: «unavailable» не должен молча превращаться в ноль и
            # выглядеть как честное «влажность 0, значит выключить».
            role = self._sensor_roles.get((entity_id, fsm_entity_id))
            if role:
                external_ctx[role] = _as_measurement(new_state)

            logger.info(f"Routing: sensor={entity_id} → fsm={fsm_entity_id}, event={event_name}")

            await self._engine.trigger(
                entity_id=fsm_entity_id,
                event=event_name,
                external_ctx=external_ctx,
            )

    #: Триггер пересмотра вентиляции при смене глобального переключателя.
    #: Отдельное имя, а не `temperature_changed`: показание датчика и решение
    #: владельца — разные поводы (у перехода может быть больше одного триггера,
    #: конституция I). Смена сезона обязана пересобрать и режим, а на каждое
    #: показание датчика режим намеренно не пересобирается (research.md D7).
    SETTINGS_CHANGED: str = "settings_changed"

    async def route_settings_change(self, context: dict[str, Any] | None = None) -> None:
        """Пересмотреть автоматы вентиляции при смене глобального переключателя.

        Переключатели вентиляции — выключатель владельца, фиче-флаг дома, сезон и
        модификаторы проветривания/вытяжки — меняются в Home Assistant, а не от
        датчика. Автомат вентиляции ждёт показания температуры, поэтому без этого
        пересмотра выключение владельца не действовало, пока датчик молчал
        (боевой разбор 2026-10-12: рекуператор дул сырым притоком на 91 % больше
        часа при выключенном выключателе).

        Признак «обогрев работает» считается здесь же, как в
        `route_state_change`, и тоже **диагностический**: с 2026-10-12 правило
        «вентиляция при обогреве выключается» отменено (research.md D22, FR-055),
        признак лишь попадает в журнал решения.

        Args:
            context: Контекст события с уже прочитанными глобальными значениями.

        Returns:
            Ничего.
        """
        if context is None:
            context = {}
        get_all_states = getattr(self._engine, "get_all_states", None)
        if get_all_states is None:
            return
        for fsm_entity_id in list(get_all_states().keys()):
            if "_ventilation_modes_" not in fsm_entity_id:
                continue
            external_ctx = {**context}
            heating = self._room_heating_active(fsm_entity_id)
            if heating is not None:
                external_ctx["heating_active"] = heating
            logger.info(
                f"Routing: settings_changed → fsm={fsm_entity_id}, heating_active={heating}"
            )
            await self._engine.trigger(
                entity_id=fsm_entity_id,
                event=self.SETTINGS_CHANGED,
                external_ctx=external_ctx,
                respect_debounce=False,
            )
