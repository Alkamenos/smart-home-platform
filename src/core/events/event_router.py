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
from core.models.manifest import Manifest, all_sensor_entities, iter_role_entities


def as_measurement(value: str | Any) -> Any:
    """Привести показание датчика к числу, если это возможно.

    Числом — чтобы условие сравнивало числа, а не строки. Строкой — чтобы
    нечитаемое значение осталось нечитаемым: молчаливое превращение «unavailable»
    в ноль выдало бы заведомо ложное решение за честное.

    Общая для маршрутизатора (условия читают числа) и для снимка локации
    (спека 016): и там, и там показание датчика приходит одной строкой.

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
            *all_sensor_entities(room.sensors),
            *(getattr(device, "id", None) for device in (room.devices or [])),
        ]
        for entity_id in candidates:
            if entity_id and entity_id not in seen:
                seen.add(entity_id)
                entities.append(entity_id)

    # Особые зоны наблюдения (спека 016): у них нет устройств, только датчики.
    # Без них подписка HA не отдавала бы события погоды и почвы, и снимок локации
    # оставался бы пустым, хотя датчики в манифесте описаны.
    for location in getattr(manifest, "locations", []) or []:
        for entity_id in all_sensor_entities(location.sensors):
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
        # Освещённость: роль `lux` (исторически — в шаблонах света) и её синоним
        # `illuminance` из спеки 016. Синоним шлёт то же `brightness_changed`,
        # иначе светильник комнаты с привязкой `illuminance` молчал бы, и
        # добавляет свой `illuminance_changed` для наблюдателей.
        "lux": ["brightness_changed"],
        "illuminance": ["brightness_changed", "illuminance_changed"],
        "contact": ["opened", "closed"],
        # Роли наблюдения (спека 016, FR-005). Автоматов у них нет, но роль
        # обязана быть известна маршрутизатору: неизвестная роль не попадает в
        # маршруты, а её датчик — в подписку HA, и событий от него не придёт.
        "pressure": ["pressure_changed"],
        "wind_speed": ["wind_speed_changed"],
        "wind_gust": ["wind_gust_changed"],
        "rain": ["rain_changed"],
        "uv_index": ["uv_index_changed"],
        "co2": ["co2_changed"],
        "soil_moisture": ["soil_moisture_changed"],
        "soil_temperature": ["soil_temperature_changed"],
        "soil_ph": ["soil_ph_changed"],
        "soil_ec": ["soil_ec_changed"],
        "battery": ["battery_changed"],
        # Детекции камер (спека 017): «человек / животное / машина». Наблюдение,
        # автоматов у них нет, но роль объявлена, чтобы маршрутизатор не считал
        # её неизвестной и не писал предупреждение на каждую комнату с камерой.
        "person": ["person_detected", "person_cleared"],
        "animal": ["animal_detected", "animal_cleared"],
        "vehicle": ["vehicle_detected", "vehicle_cleared"],
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
        self._sensor_roles: dict[
            tuple[str, str], str
        ] = {}  # Комната автомата и климат-автоматы комнаты: по ним в контекст события
        #: Последнее измерение роли по паре «автомат, роль»: нужно пересмотру по
        #: смене настройки, у которого нет собственного показания датчика.
        self._last_measurements: dict[tuple[str, str], Any] = {}
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
            for sensor_type, sensor_id in iter_role_entities(room.sensors):
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
        self._last_measurements.clear()
        self._fsm_to_room.clear()
        self._room_climate_fsms.clear()
        self._build_mapping()

    def get_mapping(self, sensor_id: str) -> list[tuple[str, str]]:
        """Get FSM mappings for a sensor."""
        return list(self._sensor_to_fsms.get(sensor_id, []))

    def get_mapping_for_sensor(self, sensor_id: str) -> list[tuple[str, str]]:
        """Get FSM mappings for a sensor (alias for get_mapping)."""
        return self.get_mapping(sensor_id)

    def mapped_sensors(self) -> list[str]:
        """Датчики, показания которых роутер доносит до автоматов.

        Нужен сверке при подключении: Home Assistant присылает событие только
        при изменении, поэтому после перезапуска платформы молчащий датчик не
        попадает в контекст автоматов, и решения принимаются по устаревшему
        значению (B40).

        Returns:
            Отсортированный список идентификаторов сущностей.
        """
        return sorted(self._sensor_to_fsms)

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
                external_ctx[role] = as_measurement(new_state)
                # Последнее известное значение роли — чтобы пересмотр по смене
                # настройки (`settings_changed`) видел те же показания, что и
                # событие датчика: без этого условия вентиляции отказывали
                # `guard_data_missing`, и выключатель владельца не пересчитывал
                # режим (боевой разбор 2026-10-14).
                self._last_measurements[(fsm_entity_id, role)] = external_ctx[role]

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

    def settings_context(self, fsm_entity_id: str) -> dict[str, Any]:
        """Общий контекст пересмотра настроек для одного автомата.

        Последние показания датчиков комнаты и признак работы обогрева. Один
        источник для маршрутизатора и сторожа вентиляции: два пути, собранные
        по-разному, расходились — сторож подтверждал решение без уличной
        температуры и сезона, и условие «приток по погоде» отказывало
        `guard_data_missing` по 288 раз в сутки (B63).

        Args:
            fsm_entity_id: Автомат, для которого собирается контекст.

        Returns:
            Контекст: показания комнаты (роль → значение) и ``heating_active``,
            если он известен.
        """
        context: dict[str, Any] = {}
        for (fsm_id, role), value in self._last_measurements.items():
            if fsm_id == fsm_entity_id:
                context.setdefault(role, value)
        heating = self._room_heating_active(fsm_entity_id)
        if heating is not None:
            context["heating_active"] = heating
        return context

    async def route_settings_change(self, context: dict[str, Any] | None = None) -> None:
        """Пересмотреть автоматы при смене глобального переключателя.

        Переключатели живут в Home Assistant, а не приходят от датчика:
        выключатель владельца, фиче-флаг дома, сезон и модификаторы для
        вентиляции; «кто-то дома», «дома собаки», разрешение закрывать ночью и
        аварийный флаг для штор. Автомат вентиляции ждёт показания температуры,
        а шторы датчиков не слушают вовсе, поэтому без этого пересмотра решение
        владельца не доходило бы до них (боевой разбор 2026-10-12: рекуператор
        дул сырым притоком на 91 % больше часа при выключенном выключателе).

        Пересматриваются автоматы, которые объявили ``settings_changed`` в
        своих переходах (``engine.entities_with_trigger``): вентиляция и шторы.
        Раньше фильтр был по подстроке имени — это ломается при добавлении
        второго домена.

        Признак «обогрев работает» считается здесь же, как в
        `route_state_change`, и **диагностический**: с 2026-10-12 правило
        «вентиляция при обогреве выключается» отменено (research.md D22, FR-055),
        признак лишь попадает в журнал решения.

        Args:
            context: Контекст события с уже прочитанными глобальными значениями.

        Returns:
            Ничего.
        """
        if context is None:
            context = {}
        entity_ids = self._engine.entities_with_trigger(self.SETTINGS_CHANGED)
        for fsm_entity_id in entity_ids:
            external_ctx = {**context}
            # Последние показания датчиков комнаты: смена настройки не несёт
            # собственного значения, а условиям вентиляции нужны температура и
            # влажность. Без них пересмотр отказывал `guard_data_missing`, и
            # решение владельца (выключатель, сезон, проветривание) не доходило.
            # Тот же контекст спрашивает сторож вентиляции (B63).
            external_ctx.update(self.settings_context(fsm_entity_id))
            heating = external_ctx.get("heating_active")
            logger.info(
                f"Routing: settings_changed → fsm={fsm_entity_id}, heating_active={heating}"
            )
            await self._engine.trigger(
                entity_id=fsm_entity_id,
                event=self.SETTINGS_CHANGED,
                external_ctx=external_ctx,
                respect_debounce=False,
            )
