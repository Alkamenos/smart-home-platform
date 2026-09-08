"""
Manifest Generator - Генератор автоматов из манифеста

Читает манифест и создаёт:
- Определения FSM для каждого устройства
- Маппинги для каждого сенсора
- Правила автоматизации
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.fsm import FSMDefinition, Transition


@dataclass
class TriggerMapping:
    """Маппинг триггера от сенсора к автомату"""
    source_entity: str
    source_value: str  # "on" | "off" | числовое значение
    target_entity: str
    trigger: str
    context_builder: Callable[[dict], dict] = field(default_factory=lambda: lambda e: {})


@dataclass
class GeneratorResult:
    """Результат генерации автоматов"""
    lighting_definitions: list[FSMDefinition]
    lighting_mappings: list[TriggerMapping]
    climate_definitions: list[FSMDefinition]
    climate_mappings: list[TriggerMapping]
    ventilation_definitions: list[FSMDefinition]
    ventilation_mappings: list[TriggerMapping]
    automation_rules: dict[str, Any]


class ManifestAutomationGenerator:
    """
    Генератор автоматов из манифеста.

    Читает манифест и создаёт:
    - Определения FSM для каждого устройства
    - Маппинги для каждого сенсора
    - Правила автоматизации
    """

    def __init__(self, manifest: dict, logger=None):
        self._manifest = manifest
        self._logger = logger or _DummyLogger()

    def generate_all(self) -> GeneratorResult:
        """Генерирует все автоматы и маппинги"""
        return GeneratorResult(
            lighting_definitions=self._generate_lighting(),
            lighting_mappings=self._generate_lighting_mappings(),
            climate_definitions=self._generate_climate(),
            climate_mappings=self._generate_climate_mappings(),
            ventilation_definitions=self._generate_ventilation(),
            ventilation_mappings=self._generate_ventilation_mappings(),
            automation_rules=self._extract_automation_rules()
        )

    def _generate_lighting(self) -> list[FSMDefinition]:
        """Генерация автоматов освещения из манифеста"""
        definitions = []

        for device in self._manifest.get("devices", {}).get("lighting", []):
            entity_id = device["id"]
            room = device.get("room", entity_id.split(".")[-1])
            motion_timeout = device.get("motion_timeout_sec", 300)
            manual_lockout = self._get_manual_lockout("lighting")

            definition = FSMDefinition(
                entity_id=entity_id,
                states=("OFF", "ON_SCHEDULE", "ON_MOTION", "MANUAL"),
                initial="OFF",
                transitions=(
                    # Включение по расписанию
                    Transition(
                        from_state="OFF",
                        to_state="ON_SCHEDULE",
                        trigger="schedule_on",
                        guard=lambda ctx, r=room, d=device: self._is_schedule_time(ctx, d),
                        priority=10,
                        reason="Включение по расписанию",
                        attributes={"entity_id": entity_id}
                    ),
                    # Выключение по расписанию
                    Transition(
                        from_state="ON_SCHEDULE",
                        to_state="OFF",
                        trigger="schedule_off",
                        guard=lambda ctx, r=room, d=device: not self._is_schedule_time(ctx, d),
                        priority=10,
                        reason="Выключение по расписанию",
                        attributes={"entity_id": entity_id}
                    ),
                    # Включение по движению
                    Transition(
                        from_state=("OFF", "ON_SCHEDULE"),
                        to_state="ON_MOTION",
                        trigger="motion_detected",
                        guard=lambda ctx, r=room: ctx.get(f"{r}_motion_sensor", False),
                        priority=20,
                        reason="Обнаружено движение",
                        attributes={"entity_id": entity_id},
                        timeout_sec=motion_timeout
                    ),
                    # Таймаут без движения
                    Transition(
                        from_state="ON_MOTION",
                        to_state="OFF",
                        trigger="timeout",
                        priority=10,
                        reason="Таймаут без движения",
                        attributes={"entity_id": entity_id}
                    ),
                    # Ручное вмешательство
                    Transition(
                        from_state="*",
                        to_state="MANUAL",
                        trigger="manual_change",
                        priority=100,
                        reason="Ручное вмешательство",
                        
                        manual_lockout_min=manual_lockout
                    ),
                    # Возврат из MANUAL после таймаута
                    Transition(
                        from_state="MANUAL",
                        to_state="OFF",
                        trigger="timeout",
                        guard=lambda ctx, r=room: self._check_manual_timeout(ctx, r),
                        priority=50,
                        reason="Автоматическое восстановление после ручного управления"
                    ),
                )
            )
            definitions.append(definition)

        return definitions

    def _generate_lighting_mappings(self) -> list[TriggerMapping]:
        """Генерация маппингов для освещения"""
        mappings = []

        for device in self._manifest.get("devices", {}).get("lighting", []):
            if "motion_sensor" in device:
                motion_sensor = device["motion_sensor"]
                entity_id = device["id"]
                room = device.get("room", entity_id.split(".")[-1])

                # Датчик движения on
                mappings.append(TriggerMapping(
                    source_entity=motion_sensor,
                    source_value="on",
                    target_entity=entity_id,
                    trigger="motion_detected",
                    context_builder=lambda e, r=room: {f"{r}_motion_sensor": True}
                ))
                # Датчик движения off
                mappings.append(TriggerMapping(
                    source_entity=motion_sensor,
                    source_value="off",
                    target_entity=entity_id,
                    trigger="motion_cleared",
                    context_builder=lambda e, r=room: {f"{r}_motion_sensor": False}
                ))

        return mappings

    def _generate_climate(self) -> list[FSMDefinition]:
        """Генерация автоматов климата из манифеста"""
        definitions = []

        for device in self._manifest.get("devices", {}).get("climate", []):
            entity_id = device["id"]
            room = device.get("room", entity_id.split(".")[-1])
            target = device.get("target", 22.0)
            hysteresis = device.get("hysteresis", 0.5)
            modes = device.get("modes", ["heat", "cool", "auto"])
            manual_lockout = self._get_manual_lockout("climate")

            definition = FSMDefinition(
                entity_id=entity_id,
                states=("IDLE", "HEATING", "COOLING", "SAFETY_LOCKOUT", "AWAY"),
                initial="IDLE",
                transitions=(
                    # Включение нагрева
                    Transition(
                        from_state="IDLE",
                        to_state="HEATING",
                        trigger="temp_low",
                        guard=lambda ctx, r=room, t=target, h=hysteresis: (
                            ctx.get(f"{r}_temp_current", 0) < t - h and
                            ctx.get(f"{r}_mode", "auto") in ("heat", "auto")
                        ),
                        priority=30,
                        reason="Температура ниже целевой",
                        attributes={"entity_id": entity_id, "hvac_mode": "heat"}
                    ),
                    # Выключение нагрева
                    Transition(
                        from_state="HEATING",
                        to_state="IDLE",
                        trigger="temp_reached",
                        guard=lambda ctx, r=room, t=target: (
                            ctx.get(f"{r}_temp_current", 0) >= t
                        ),
                        priority=30,
                        reason="Температура достигнута",
                        attributes={"entity_id": entity_id}
                    ),
                    # Включение охлаждения
                    Transition(
                        from_state="IDLE",
                        to_state="COOLING",
                        trigger="temp_high",
                        guard=lambda ctx, r=room, t=target, h=hysteresis: (
                            ctx.get(f"{r}_temp_current", 0) > t + h and
                            ctx.get(f"{r}_mode", "auto") in ("cool", "auto")
                        ),
                        priority=30,
                        reason="Температура выше целевой",
                        attributes={"entity_id": entity_id, "hvac_mode": "cool"}
                    ),
                    # Выключение охлаждения
                    Transition(
                        from_state="COOLING",
                        to_state="IDLE",
                        trigger="temp_reached",
                        guard=lambda ctx, r=room, t=target: (
                            ctx.get(f"{r}_temp_current", 0) <= t
                        ),
                        priority=30,
                        reason="Температура достигнута",
                        attributes={"entity_id": entity_id}
                    ),
                    # Режим отсутствия
                    Transition(
                        from_state="*",
                        to_state="AWAY",
                        trigger="away_mode_on",
                        priority=40,
                        reason="Режим отсутствия включён",
                        attributes={"entity_id": entity_id}
                    ),
                    Transition(
                        from_state="AWAY",
                        to_state="IDLE",
                        trigger="away_mode_off",
                        priority=40,
                        reason="Режим отсутствия выключен",
                        attributes={"entity_id": entity_id}
                    ),
                    # Блокировка безопасности
                    Transition(
                        from_state="*",
                        to_state="SAFETY_LOCKOUT",
                        trigger="safety_alarm",
                        priority=200,
                        reason="Сработала система безопасности",
                        attributes={"entity_id": entity_id}
                    ),
                    Transition(
                        from_state="SAFETY_LOCKOUT",
                        to_state="IDLE",
                        trigger="safety_reset",
                        priority=200,
                        reason="Блокировка сброшена",
                        attributes={"entity_id": entity_id}
                    ),
                    # Ручное вмешательство
                    Transition(
                        from_state="*",
                        to_state="MANUAL",
                        trigger="manual_change",
                        priority=100,
                        reason="Ручное вмешательство",
                        
                        manual_lockout_min=manual_lockout
                    ),
                )
            )
            definitions.append(definition)

        return definitions

    def _generate_climate_mappings(self) -> list[TriggerMapping]:
        """Генерация маппингов для климата"""
        mappings = []

        for device in self._manifest.get("devices", {}).get("climate", []):
            if "sensor" in device:
                sensor = device["sensor"]
                entity_id = device["id"]
                room = device.get("room", entity_id.split(".")[-1])

                # Маппинг температуры
                mappings.append(TriggerMapping(
                    source_entity=sensor,
                    source_value="*",  # Любое значение
                    target_entity=entity_id,
                    trigger="temperature_changed",
                    context_builder=lambda e, r=room: {
                        f"{r}_temp_current": float(e.get("new_state", {}).get("state", 0))
                    }
                ))

        return mappings

    def _generate_ventilation(self) -> list[FSMDefinition]:
        """Генерация автоматов вентиляции из манифеста"""
        definitions = []

        for device in self._manifest.get("devices", {}).get("ventilation", []):
            entity_id = device["id"]
            room = device.get("room", entity_id.split(".")[-1])
            humidity_threshold = device.get("humidity_threshold", 65)
            timeout_sec = device.get("timeout_sec", 1800)
            manual_lockout = self._get_manual_lockout("ventilation")

            definition = FSMDefinition(
                entity_id=entity_id,
                states=("OFF", "ON_HUMIDITY", "MANUAL"),
                initial="OFF",
                transitions=(
                    # Включение по влажности
                    Transition(
                        from_state="OFF",
                        to_state="ON_HUMIDITY",
                        trigger="humidity_high",
                        guard=lambda ctx, r=room, t=humidity_threshold: (
                            ctx.get(f"{r}_humidity", 0) > t
                        ),
                        priority=20,
                        reason="Влажность выше порога",
                        attributes={"entity_id": entity_id},
                        timeout_sec=timeout_sec
                    ),
                    # Выключение по таймауту
                    Transition(
                        from_state="ON_HUMIDITY",
                        to_state="OFF",
                        trigger="timeout",
                        priority=10,
                        reason="Таймаут вентиляции",
                        attributes={"entity_id": entity_id}
                    ),
                    # Выключение когда влажность упала
                    Transition(
                        from_state="ON_HUMIDITY",
                        to_state="OFF",
                        trigger="humidity_low",
                        guard=lambda ctx, r=room, t=humidity_threshold: (
                            ctx.get(f"{r}_humidity", 0) < t - 5  # гистерезис 5%
                        ),
                        priority=20,
                        reason="Влажность в норме",
                        attributes={"entity_id": entity_id}
                    ),
                    # Ручное вмешательство
                    Transition(
                        from_state="*",
                        to_state="MANUAL",
                        trigger="manual_change",
                        priority=100,
                        reason="Ручное вмешательство",
                        
                        manual_lockout_min=manual_lockout
                    ),
                )
            )
            definitions.append(definition)

        return definitions

    def _generate_ventilation_mappings(self) -> list[TriggerMapping]:
        """Генерация маппингов для вентиляции"""
        mappings = []

        for device in self._manifest.get("devices", {}).get("ventilation", []):
            if "humidity_sensor" in device:
                sensor = device["humidity_sensor"]
                entity_id = device["id"]
                room = device.get("room", entity_id.split(".")[-1])
                threshold = device.get("humidity_threshold", 65)

                # Маппинг влажности
                mappings.append(TriggerMapping(
                    source_entity=sensor,
                    source_value="*",
                    target_entity=entity_id,
                    trigger="humidity_changed",
                    context_builder=lambda e, r=room: {
                        f"{r}_humidity": float(e.get("new_state", {}).get("state", 0))
                    }
                ))

        return mappings

    def _extract_automation_rules(self) -> dict[str, Any]:
        """Извлечение правил автоматизации из манифеста"""
        return self._manifest.get("automation_rules", {})

    def _get_manual_lockout(self, device_type: str) -> float:
        """Получить время блокировки автоматики для типа устройства"""
        rules = self._manifest.get("automation_rules", {})
        return rules.get(device_type, {}).get("manual_lockout_min", 60)

    def _is_schedule_time(self, ctx: dict, device: dict) -> bool:
        """Проверить, сейчас ли время расписания"""
        from datetime import datetime
        schedule = device.get("schedule", "00:00-23:59")
        start, end = schedule.split("-")
        now = datetime.now().strftime("%H:%M")
        return start <= now <= end

    def _check_manual_timeout(self, ctx: dict, room: str) -> bool:
        """Проверить истёк ли таймаут ручного управления"""
        entered_at = ctx.get(f"{room}_manual_entered_at", 0)
        if entered_at <= 0:
            return False
        elapsed_min = (time.time() - entered_at) / 60
        return elapsed_min >= 60  # 60 минут по умолчанию


class _DummyLogger:
    """Заглушка логгера если не передан"""
    def debug(self, msg, **kwargs): pass
    def info(self, msg, **kwargs): pass
    def warning(self, msg, **kwargs): pass
    def error(self, msg, **kwargs): pass
