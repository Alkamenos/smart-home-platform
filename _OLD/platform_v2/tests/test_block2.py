#!/usr/bin/env python3
"""Тесты для Блока 2: Синхронизация, Контекст, Блокировки"""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from OLD.platform_v2.core.sync_engine import SyncEngine
from OLD.platform_v2.core.room_context import RoomContextBuilder, TimeOfDay, Season, Presence
from OLD.platform_v2.core.override_manager import OverrideManager

class TestSyncEngine:
    def test_set_desired_and_get(self):
        """Установка и получение желаемого состояния"""
        sync = SyncEngine()
        sync.set_desired("light.test", "on", reason="motion detected")

        desired = sync.get_desired("light.test")
        assert desired is not None
        assert desired.state == "on"
        assert desired.reason == "motion detected"

    def test_divergence_detection(self):
        """Обнаружение расхождения"""
        sync = SyncEngine(grace_sec=1)

        # Устанавливаем желаемое
        sync.set_desired("light.test", "on")

        # Реальное состояние другое
        sync.update_actual("light.test", "off")

        # Должно быть расхождение
        divergences = sync.get_divergences()
        assert len(divergences) == 1
        assert divergences[0].entity_id == "light.test"

    def test_sync_resolves_divergence(self):
        """Синхронизация устраняет расхождение"""
        applied = []

        def mock_apply(entity_id, state, attrs):
            applied.append((entity_id, state))

        sync = SyncEngine(grace_sec=0)
        sync.set_apply_callback(mock_apply)

        sync.set_desired("light.test", "on")
        sync.update_actual("light.test", "off")

        # Запускаем синхронизацию
        result = sync.sync_tick()

        assert "light.test" in result
        # Применяется только один раз через sync_tick
        assert len(applied) == 1
        assert applied[0] == ("light.test", "on")

    def test_manual_lock_blocks_sync(self):
        """Ручная блокировка предотвращает синхронизацию"""
        applied = []

        def mock_apply(entity_id, state, attrs):
            applied.append((entity_id, state))

        sync = SyncEngine(grace_sec=0)
        sync.set_apply_callback(mock_apply)

        # Сначала блокируем
        sync.set_manual_lock("light.test", duration_min=60)

        # Потом устанавливаем желаемое
        sync.set_desired("light.test", "on")
        sync.update_actual("light.test", "off")

        result = sync.sync_tick()

        assert "light.test" not in result
        assert len(applied) == 0

class TestRoomContext:
    def test_build_basic_context(self):
        """Построение базового контекста"""
        builder = RoomContextBuilder()

        # Мокаем чтение состояний
        states = {
            "input_boolean.zima": "off",
            "input_boolean.my_doma": "on",
            "input_boolean.party_mode": "off",
        }

        builder.set_state_reader(lambda e: states.get(e))
        builder.set_time_reader(lambda: time.struct_time((2026, 9, 6, 14, 30, 0, 0, 0, 0)))

        ctx = builder.build("living_room")

        assert ctx.room_id == "living_room"
        assert ctx.season == Season.SUMMER
        assert ctx.time_of_day == TimeOfDay.DAY
        assert ctx.presence == Presence.HOME_DAY
        assert not ctx.party_mode

    def test_night_time_detection(self):
        """Определение ночного времени"""
        builder = RoomContextBuilder()
        builder.set_time_reader(lambda: time.struct_time((2026, 9, 6, 2, 0, 0, 0, 0, 0)))

        ctx = builder.build("living_room")
        assert ctx.time_of_day == TimeOfDay.NIGHT
        assert ctx.is_night()

    def test_winter_detection(self):
        """Определение зимнего сезона"""
        builder = RoomContextBuilder()

        states = {"input_boolean.zima": "on"}
        builder.set_state_reader(lambda e: states.get(e))

        ctx = builder.build("living_room")
        assert ctx.season == Season.WINTER

class TestOverrideManager:
    def test_set_and_check_override(self):
        """Установка и проверка блокировки"""
        om = OverrideManager()

        om.set_override("light.test", source="button", reason="manual press")

        assert om.is_overridden("light.test")
        override = om.get_override("light.test")
        assert override.source == "button"
        assert override.reason == "manual press"

    def test_override_expiry(self):
        """Истечение блокировки"""
        om = OverrideManager()

        om.set_override("light.test", timeout_min=0)  # Сразу истекает

        # Должна быть неактивна
        assert not om.is_overridden("light.test")

    def test_release_override(self):
        """Снятие блокировки"""
        om = OverrideManager()

        om.set_override("light.test", timeout_min=60)
        assert om.is_overridden("light.test")

        om.release("light.test")
        assert not om.is_overridden("light.test")

    def test_release_all(self):
        """Снятие всех блокировок"""
        om = OverrideManager()

        om.set_override("light.test1")
        om.set_override("light.test2")

        om.release_all()

        assert not om.is_overridden("light.test1")
        assert not om.is_overridden("light.test2")

    def test_history_tracking(self):
        """История блокировок"""
        om = OverrideManager()

        om.set_override("light.test1", source="button")
        om.set_override("light.test2", source="dashboard")

        history = om.get_history()
        assert len(history) == 2

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
