#!/usr/bin/env python3
"""Тесты для фич платформы"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from OLD.platform_v2.core.sync_engine import SyncEngine
from OLD.platform_v2.core.room_context import RoomContext, TimeOfDay, Presence
from OLD.platform_v2.features.lighting import LightingFeature
from OLD.platform_v2.features.ventilation import VentilationFeature

def create_lighting_config():
    """Создать тестовую конфигурацию освещения"""
    return {
        "enabled": True,
        "color_temp": {
            "day_kelvin": 5000,
            "night_kelvin": 2200,
            "warm_from": "21:00",
            "night_from": "23:00",
            "morning_to": "08:00",
        },
        "override_timeout_min": 60,
        "groups": {
            "living_room": {
                "name": "Гостиная",
                "room": "living_room",
                "devices": ["light.living_room"],
                "fsm": {
                    "states": ["OFF", "ON_MOTION", "ON_SCHEDULE", "MANUAL_LOCK"],
                    "initial": "OFF",
                    "transitions": [
                        {
                            "from": ["OFF"],
                            "to": "ON_MOTION",
                            "trigger": "motion",
                            "guard": "dark and motion_mode != 'Выкл'",
                            "priority": 30,
                            "why": "Включение по движению"
                        },
                        {
                            "from": ["ON_MOTION"],
                            "to": "OFF",
                            "trigger": "no_motion_timeout",
                            "priority": 10,
                            "why": "Выключение по таймеру"
                        },
                    ]
                },
                "features": {
                    "motion": {"enabled": True},
                }
            }
        }
    }

def create_ventilation_config():
    """Создать тестовую конфигурацию вентиляции"""
    return {
        "enabled": True,
        "devices": [
            {"entity": "fan.living_room", "name": "Рекуператор"}
        ],
        "setpoints": {
            "co2_boost_threshold": 1000,
            "humidity_boost_threshold": 70,
            "winter_pause_temp": -10,
        }
    }

class TestLightingFeature:
    def test_initial_state_off(self):
        """Освещение должно быть выключено при старте"""
        sync = SyncEngine()
        config = create_lighting_config()
        feature = LightingFeature(config, sync)

        status = feature.get_status()
        assert status["fsm_states"]["light.living_room"] == "OFF"

    def test_motion_turns_on_light_when_dark(self):
        """Движение должно включать свет когда темно"""
        sync = SyncEngine()
        config = create_lighting_config()
        feature = LightingFeature(config, sync)

        room_ctx = RoomContext(
            room_id="living_room",
            presence=Presence.HOME_DAY,
            time_of_day=TimeOfDay.EVENING,
            is_dark=True,
            motion=True
        )

        decision = feature.decide(room_ctx)

        # Должно быть действие включения
        assert len(decision.actions) > 0
        action = decision.actions[0]
        assert action.entity_id == "light.living_room"
        assert action.state == "on"

    def test_motion_blocked_when_light(self):
        """Движение не должно включать свет когда светло"""
        sync = SyncEngine()
        config = create_lighting_config()
        feature = LightingFeature(config, sync)

        room_ctx = RoomContext(
            room_id="living_room",
            presence=Presence.HOME_DAY,
            time_of_day=TimeOfDay.DAY,
            is_dark=False,
            motion=True
        )

        decision = feature.decide(room_ctx)

        # FSM должен остаться в OFF
        assert decision.fsm_state == "OFF"

    def test_apply_sets_desired_state(self):
        """Применение решения должно устанавливать желаемое состояние"""
        sync = SyncEngine()
        config = create_lighting_config()
        feature = LightingFeature(config, sync)

        room_ctx = RoomContext(
            room_id="living_room",
            presence=Presence.HOME_DAY,
            time_of_day=TimeOfDay.EVENING,
            is_dark=True,
            motion=True
        )

        decision = feature.decide(room_ctx)
        feature.apply(decision)

        # Проверяем, что желаемое состояние установлено
        desired = sync.get_desired("light.living_room")
        assert desired is not None
        assert desired.state == "on"

class TestVentilationFeature:
    def test_initial_state_normal(self):
        """Вентиляция должна быть в NORMAL при старте"""
        sync = SyncEngine()
        config = create_ventilation_config()
        feature = VentilationFeature(config, sync)

        status = feature.get_status()
        assert status["fsm_states"]["fan.living_room"] == "NORMAL"

    def test_high_co2_triggers_boost(self):
        """Высокий CO2 должен запускать BOOST"""
        sync = SyncEngine()
        config = create_ventilation_config()
        feature = VentilationFeature(config, sync)

        room_ctx = RoomContext(
            room_id="living_room",
            co2=1200,  # Выше порога
            humidity=50
        )

        decision = feature.decide(room_ctx)

        # Должен быть BOOST
        assert decision.fsm_state == "BOOST"
        action = decision.actions[0]
        assert action.attributes["percentage"] == 100

    def test_cold_outdoor_triggers_winter_pause(self):
        """Очень холодная погода должна вызывать зимнюю паузу"""
        sync = SyncEngine()
        config = create_ventilation_config()
        feature = VentilationFeature(config, sync)

        # Мокаем температуру на улице
        feature._get_outdoor_temp = lambda: -15.0

        room_ctx = RoomContext(
            room_id="living_room",
            co2=600,
            humidity=50
        )

        decision = feature.decide(room_ctx)

        # Должна быть зимняя пауза
        assert decision.fsm_state == "WINTER_PAUSE"
        action = decision.actions[0]
        assert action.state == "off"

    def test_normal_co2_stays_normal(self):
        """Нормальный CO2 должен оставлять вентиляцию в NORMAL"""
        sync = SyncEngine()
        config = create_ventilation_config()
        feature = VentilationFeature(config, sync)

        room_ctx = RoomContext(
            room_id="living_room",
            co2=600,  # Норма
            humidity=50
        )

        decision = feature.decide(room_ctx)

        assert decision.fsm_state == "NORMAL"
        action = decision.actions[0]
        assert action.attributes["percentage"] == 40

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
