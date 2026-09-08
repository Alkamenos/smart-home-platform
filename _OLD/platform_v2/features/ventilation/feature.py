#!/usr/bin/env python3
"""
Ventilation Feature V2 — управление вентиляцией.

Реагирует на:
- Уровень CO2 (boost при высоком значении)
- Влажность (вытяжка при высокой влажности)
- Температуру на улице (зимняя пауза)
- Ручное вмешательство
"""
from typing import Optional
from OLD.platform_v2.core.feature_base import FeatureBase, FeatureDecision, Action
from OLD.platform_v2.core.fsm_engine import FSMEngine, FSMDefinition
from OLD.platform_v2.core.room_context import RoomContext
from OLD.platform_v2.core.sync_engine import SyncEngine

# Пороги для автоматических режимов
CO2_BOOST_THRESHOLD = 1000  # ppm
HUMIDITY_BOOST_THRESHOLD = 70  # %
WINTER_PAUSE_TEMP = -10.0  # °C

# Пресеты вентиляции
PRESET_NORMAL = "Рекуперация"
PRESET_BOOST = "Приток MAX"
PRESET_EXHAUST = "Вытяжка MAX"
PRESET_NIGHT = "Рекуперация (ночь)"
PRESET_OFF = "OFF"

class VentilationFeature(FeatureBase):
    """Фича управления вентиляцией"""

    def __init__(self, config: dict, sync_engine: SyncEngine):
        super().__init__("ventilation", config, sync_engine)
        self._fsm = FSMEngine()
        self._devices = config.get("devices", [])
        self._setpoints = config.get("setpoints", {})

        # Пороги из конфигурации
        self._co2_threshold = self._setpoints.get("co2_boost_threshold", CO2_BOOST_THRESHOLD)
        self._humidity_threshold = self._setpoints.get("humidity_boost_threshold", HUMIDITY_BOOST_THRESHOLD)
        self._winter_pause_temp = self._setpoints.get("winter_pause_temp", WINTER_PAUSE_TEMP)

        # Регистрируем FSM для каждого устройства
        self._register_fsm()

    def _register_fsm(self):
        """Зарегистрировать FSM для всех устройств"""
        definition = self._create_fsm_definition()

        for device in self._devices:
            entity_id = device.get("entity")
            if entity_id:
                self._fsm.register(entity_id, definition)

    def _create_fsm_definition(self) -> FSMDefinition:
        """Создать определение автомата вентиляции"""
        return FSMDefinition(
            states=["NORMAL", "BOOST", "NIGHT", "AWAY", "WINTER_PAUSE", "MANUAL_LOCK"],
            initial="NORMAL",
            transitions=[
                # CO2 высокий -> BOOST
                {
                    "from": ["NORMAL", "NIGHT"],
                    "to": "BOOST",
                    "trigger": "co2_high",
                    "priority": 50,
                    "why": "Высокий CO2 - нужен приток MAX"
                },
                # Влажность высокая -> BOOST (вытяжка)
                {
                    "from": ["NORMAL", "NIGHT"],
                    "to": "BOOST",
                    "trigger": "humidity_high",
                    "priority": 45,
                    "why": "Высокая влажность - нужна вытяжка"
                },
                # CO2 в норме -> возврат
                {
                    "from": ["BOOST"],
                    "to": "NORMAL",
                    "trigger": "co2_normal",
                    "priority": 10,
                    "why": "CO2 в норме - возврат к обычной вентиляции"
                },
                # Влажность в норме -> возврат
                {
                    "from": ["BOOST"],
                    "to": "NORMAL",
                    "trigger": "humidity_normal",
                    "priority": 10,
                    "why": "Влажность в норме - возврат"
                },
                # Зима -> пауза
                {
                    "from": ["NORMAL", "NIGHT", "BOOST", "AWAY"],
                    "to": "WINTER_PAUSE",
                    "trigger": "winter_conditions",
                    "priority": 400,
                    "why": "Зимняя пауза - очень холодно на улице"
                },
                # Зима закончилась -> возврат
                {
                    "from": ["WINTER_PAUSE"],
                    "to": "NORMAL",
                    "trigger": "winter_pause_clear",
                    "priority": 10,
                    "why": "Зимние условия устранены"
                },
                # Ручное вмешательство
                {
                    "from": ["NORMAL", "NIGHT", "BOOST", "AWAY", "WINTER_PAUSE"],
                    "to": "MANUAL_LOCK",
                    "trigger": "manual_change",
                    "priority": 100,
                    "why": "Ручное вмешательство"
                },
                # Таймер блокировки истёк
                {
                    "from": "MANUAL_LOCK",
                    "to": "NORMAL",
                    "trigger": "timeout",
                    "priority": 5,
                    "why": "Таймер блокировки истёк"
                },
            ]
        )

    def build_context(self, room_context: RoomContext) -> dict:
        """Собрать контекст для вентиляции"""
        return {
            "co2": room_context.co2 or 400,
            "humidity": room_context.humidity or 50,
            "outdoor_temp": self._get_outdoor_temp(),
            "season": room_context.season.value,
            "is_night": room_context.is_night(),
            "presence": room_context.presence.value,
        }

    def decide(self, room_context: RoomContext) -> FeatureDecision:
        """Принять решение для всех устройств вентиляции"""
        ctx = self.build_context(room_context)
        actions = []

        for device in self._devices:
            entity_id = device.get("entity")
            if not entity_id:
                continue

            # Определяем триггеры
            triggers = self._build_triggers(ctx)

            # Пробуем каждый триггер
            for trigger in triggers:
                if self._fsm.trigger(entity_id, trigger, src="автоматика", ctx=ctx):
                    break

            # Формируем действие
            state = self._fsm.get_state(entity_id)
            action = self._state_to_action(entity_id, state)
            if action:
                actions.append(action)

        return FeatureDecision(
            actions=actions,
            fsm_state=self._fsm.get_state(self._devices[0].get("entity")) if self._devices else None,
            context_snapshot=ctx
        )

    def _build_triggers(self, ctx: dict) -> list[str]:
        """Определить активные триггеры"""
        triggers = []

        co2 = ctx.get("co2", 400)
        humidity = ctx.get("humidity", 50)
        outdoor_temp = ctx.get("outdoor_temp", 0)

        # Зимние условия (проверяем что температура доступна)
        if outdoor_temp is not None and outdoor_temp < self._winter_pause_temp:
            triggers.append("winter_conditions")
        else:
            triggers.append("winter_pause_clear")

        # CO2
        if co2 >= self._co2_threshold:
            triggers.append("co2_high")
        else:
            triggers.append("co2_normal")

        # Влажность
        if humidity >= self._humidity_threshold:
            triggers.append("humidity_high")
        else:
            triggers.append("humidity_normal")

        return triggers

    def _state_to_action(self, entity_id: str, state: str) -> Optional[Action]:
        """Преобразовать состояние в действие"""
        if state is None:
            return None

        if state == "NORMAL":
            return Action(
                entity_id=entity_id,
                state="on",
                attributes={"preset_mode": PRESET_NORMAL, "percentage": 40},
                reason="FSM: NORMAL"
            )
        elif state == "BOOST":
            return Action(
                entity_id=entity_id,
                state="on",
                attributes={"preset_mode": PRESET_BOOST, "percentage": 100},
                reason="FSM: BOOST"
            )
        elif state == "NIGHT":
            return Action(
                entity_id=entity_id,
                state="on",
                attributes={"preset_mode": PRESET_NIGHT, "percentage": 10},
                reason="FSM: NIGHT"
            )
        elif state == "AWAY":
            return Action(
                entity_id=entity_id,
                state="on",
                attributes={"preset_mode": PRESET_NORMAL, "percentage": 20},
                reason="FSM: AWAY"
            )
        elif state == "WINTER_PAUSE":
            return Action(
                entity_id=entity_id,
                state="off",
                reason="FSM: WINTER_PAUSE"
            )
        elif state == "MANUAL_LOCK":
            return None

        return None

    def _get_outdoor_temp(self) -> Optional[float]:
        """Получить температуру на улице"""
        # В реальной системе читается из сенсора
        return None

    def apply(self, decision: FeatureDecision) -> None:
        """Применить решение через SyncEngine"""
        for action in decision.actions:
            # Не устанавливаем desired если устройство заблокировано вручную
            if self._sync.is_manual_locked(action.entity_id):
                continue

            self._sync.set_desired(
                entity_id=action.entity_id,
                state=action.state,
                attributes=action.attributes,
                source=action.source,
                reason=action.reason
            )

    def get_status(self) -> dict:
        """Получить статус фичи"""
        base = super().get_status()
        base.update({
            "devices": [d.get("entity") for d in self._devices],
            "fsm_states": {
                d.get("entity"): self._fsm.get_state(d.get("entity"))
                for d in self._devices
            }
        })
        return base
