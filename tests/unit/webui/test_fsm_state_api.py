"""
Тесты представления состояния автомата в ответах интерфейса (FR-017…FR-023).

Представление отличается от внутреннего состояния движка: время перехода —
настенное ISO-8601, а не монотонные часы цикла, а внутренний контекст
наружу не отдаётся.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from src.core.events.event_bus import EventBus
from src.webui.models import AutomationInfo, FSMStateView, build_all_fsm_state_views

from core import FSMDefinition, FSMEngine, State, Transition


FSM_ID = "light.kitchen_lighting_10"
DEVICE_ID = "light.kitchen"
BEHAVIOR = "lighting"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


@pytest.fixture
def engine() -> FSMEngine:
    """Движок состояний без хранилища."""
    return FSMEngine(event_bus=EventBus())


def register_fsm(engine: FSMEngine, fsm_id: str = FSM_ID, device_id: str = DEVICE_ID) -> None:
    """Зарегистрировать автомат освещения.

    Args:
        engine: Движок состояний.
        fsm_id: Идентификатор автомата.
        device_id: Устройство автомата.
    """
    engine.register_definition(
        FSMDefinition(
            entity_id=fsm_id,
            initial_state="OFF",
            states=("OFF", "ON_MOTION"),
            transitions=(
                Transition(from_state="OFF", to_state="ON_MOTION", trigger="motion_detected"),
            ),
            target_device_id=device_id,
        )
    )


class TestFSMStateView:
    """Поля представления состояния (data-model §2)."""

    def test_should_expose_contract_fields_when_built(self) -> None:
        """Представление содержит ровно поля контракта."""
        view = FSMStateView(
            fsm_id=FSM_ID,
            device_id=DEVICE_ID,
            behavior=BEHAVIOR,
            state="ON_MOTION",
            since="2026-10-01T14:23:11.482913",
            automated=True,
        )

        assert set(view.model_dump().keys()) == {
            "fsm_id",
            "device_id",
            "behavior",
            "state",
            "since",
            "automated",
        }

    def test_should_allow_null_since_when_never_transitioned(self) -> None:
        """До первого перехода время не задано (FR-017)."""
        view = FSMStateView(
            fsm_id=FSM_ID,
            device_id=DEVICE_ID,
            behavior=BEHAVIOR,
            state="OFF",
            since=None,
            automated=True,
        )

        assert view.since is None

    def test_should_mark_not_automated_when_automation_missing(self) -> None:
        """Устройство без автоматики помечается явно, а не пустым значением (FR-019)."""
        info = AutomationInfo(configured=False, reason="no_automation")

        assert info.configured is False
        assert info.reason == "no_automation"
        assert info.fsm_ids == []

    def test_should_list_fsm_ids_when_automation_configured(self) -> None:
        """Настроенная автоматика перечисляет автоматы устройства."""
        info = AutomationInfo(configured=True, fsm_ids=[FSM_ID])

        assert info.configured is True
        assert info.fsm_ids == [FSM_ID]
        assert info.reason is None


class TestBuildStateView:
    """Сборка представления из состояния движка (FR-018)."""

    def test_should_build_view_from_engine_state(self, engine: FSMEngine) -> None:
        """Состояние читается из движка на момент вызова."""
        register_fsm(engine)

        view = build_state_view(engine, FSM_ID, DEVICE_ID, "ON_MOTION", engine.get_state(FSM_ID))

        assert view.fsm_id == FSM_ID
        assert view.device_id == DEVICE_ID
        assert view.behavior == BEHAVIOR
        assert view.state == "OFF"
        assert view.automated is True

    async def test_should_use_wall_clock_not_loop_time_for_since(self, engine: FSMEngine) -> None:
        """Время перехода — настенное, а не монотонное значение цикла (R-04)."""
        register_fsm(engine)
        await engine.trigger(FSM_ID, "motion_detected")

        view = build_state_view(engine, FSM_ID, DEVICE_ID, "ON_MOTION", engine.get_state(FSM_ID))

        assert view.since is not None
        parsed = datetime.strptime(view.since, TIMESTAMP_FORMAT)
        assert parsed.year >= 2024
        assert view.since != str(engine.get_state(FSM_ID).entered_at)

    def test_should_not_expose_internal_context(self, engine: FSMEngine) -> None:
        """Внутренний контекст состояния наружу не отдаётся."""
        register_fsm(engine)
        engine._states[FSM_ID] = State(
            current_state="ON_MOTION",
            entered_at=12345.678,
            context={"secret": "value"},
        )

        view = build_state_view(engine, FSM_ID, DEVICE_ID, "ON_MOTION", engine.get_state(FSM_ID))

        assert "context" not in view.model_dump()
        assert "secret" not in view.model_dump_json()

    def test_should_fall_back_to_fsm_id_when_device_unknown(self, engine: FSMEngine) -> None:
        """Без описания устройство совпадает с идентификатором автомата."""
        view = build_state_view(engine, "unknown_fsm", None, None, None)

        assert view.fsm_id == "unknown_fsm"
        assert view.device_id == "unknown_fsm"
        assert view.behavior == ""
        assert view.state == ""
        assert view.since is None
        assert view.automated is False


class TestAllStateViews:
    """Сбор представлений для всех автоматов (FR-018)."""

    def test_should_return_view_per_registered_fsm(self, engine: FSMEngine) -> None:
        """Каждый зарегистрированный автомат даёт своё представление."""
        register_fsm(engine, FSM_ID)
        register_fsm(engine, "light.kitchen_night_light_20")

        views = build_all_state_views(engine, {DEVICE_ID})

        assert {view.fsm_id for view in views} == {
            FSM_ID,
            "light.kitchen_night_light_20",
        }

    def test_should_return_empty_list_when_no_fsms(self, engine: FSMEngine) -> None:
        """Без автоматов список пуст (FR-021)."""
        assert build_all_state_views(engine, {DEVICE_ID}) == []

    def test_should_include_states_without_definition(self, engine: FSMEngine) -> None:
        """Состояние без описания автомата тоже попадает в ответ."""
        engine._states["light.orphan_lighting_10"] = State(
            current_state="ON_MOTION",
            entered_at=0.0,
            context={},
        )

        views = build_all_state_views(engine, {"light.orphan"})

        assert [view.fsm_id for view in views] == ["light.orphan_lighting_10"]


def build_state_view(
    engine: FSMEngine,
    fsm_id: str,
    device_id: str | None,
    to_state: str | None,
    state: State | None,
) -> FSMStateView:
    """Собрать представление состояния автомата (вспомогательная функция теста)."""
    from src.webui.models import build_fsm_state_view

    return build_fsm_state_view(engine, fsm_id, device_id, to_state, state)


def build_all_state_views(engine: FSMEngine, allowed_devices: set[str]) -> list[FSMStateView]:
    """Собрать представления состояний с фильтрацией по устройствам."""
    from src.webui.models import build_all_fsm_state_views

    return build_all_fsm_state_views(engine, allowed_devices)


@pytest.mark.asyncio
async def test_should_not_cache_stale_state_when_read_twice(engine: FSMEngine) -> None:
    """Ответ отражает состояние на момент запроса, без устаревания (FR-018)."""
    register_fsm(engine)

    before = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID))
    await engine.trigger(FSM_ID, "motion_detected")
    after = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID))

    assert before.state == "OFF"
    assert after.state == "ON_MOTION"
    assert asyncio.get_event_loop().is_running()


class TestAccessFiltering:
    """Различение «без фильтрации» и «нет доступных устройств» (FR-038)."""

    def test_should_return_no_views_when_user_has_no_accessible_devices(
        self, engine: FSMEngine
    ) -> None:
        """Пустой набор доступных устройств означает отсутствие доступа, а не отказ от фильтрации."""
        register_fsm(engine)

        assert build_all_fsm_state_views(engine, set()) == []

    def test_should_return_all_views_when_filtering_disabled(self, engine: FSMEngine) -> None:
        """None означает «без фильтрации» — например, для администратора."""
        register_fsm(engine)

        views = build_all_fsm_state_views(engine, None)

        assert [view.fsm_id for view in views] == [FSM_ID]

    def test_should_filter_out_inaccessible_devices(self, engine: FSMEngine) -> None:
        """В ответ попадают только автоматы доступных устройств."""
        register_fsm(engine)
        register_fsm(engine, "light.bathroom_night_light_20", "light.bathroom")

        views = build_all_fsm_state_views(engine, {DEVICE_ID})

        assert [view.fsm_id for view in views] == [FSM_ID]


class TestTransitionTimestamp:
    """`since` — время последнего перехода, а не время чтения (FR-017)."""

    async def test_should_keep_since_stable_after_transition(self, engine: FSMEngine) -> None:
        """Время перехода не меняется при последующих чтениях."""
        register_fsm(engine)
        await engine.trigger(FSM_ID, "motion_detected")

        first = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID)).since
        await asyncio.sleep(0.02)
        second = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID)).since

        assert first is not None
        assert second == first

    async def test_should_be_none_before_first_transition(self, engine: FSMEngine) -> None:
        """До первого перехода время не задано (FR-017)."""
        register_fsm(engine)

        view = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID))

        assert view.since is None

    async def test_should_update_since_after_new_transition(self, engine: FSMEngine) -> None:
        """Новый переход обновляет время состояния."""
        register_fsm(engine)
        await engine.trigger(FSM_ID, "motion_detected")
        first = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID)).since

        engine.reset_state(FSM_ID, "OFF")
        await asyncio.sleep(0.02)
        await engine.trigger(FSM_ID, "motion_detected")
        second = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID)).since

        assert first is not None
        assert second is not None
        assert second > first

    def test_should_use_wall_clock_time_from_engine(self, engine: FSMEngine) -> None:
        """Представление берёт настенное время перехода из движка."""
        register_fsm(engine)
        engine.note_transition(FSM_ID, "2026-10-01T14:23:11.482913")

        view = build_state_view(engine, FSM_ID, DEVICE_ID, None, engine.get_state(FSM_ID))

        assert view.since == "2026-10-01T14:23:11.482913"
