"""
Тесты сохранения и восстановления состояний автоматов (FR-015, SC-016, SC-017).

Проверяют путь «переход → хранилище → перезапуск платформы»: состояние
автомата должно переживать перезапуск, недопустимое состояние не
восстанавливается, а снятый с регистрации автомат не воскресает.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from src.core.events.event_bus import EventBus
from src.core.persistence.state_persistence import StatePersistence

from core import FSMDefinition, FSMEngine, Transition


FSM_ID = "light.kitchen_lighting_10"


@pytest.fixture
def storage_path(tmp_path: Path) -> str:
    """Путь к файлу состояний во временном каталоге."""
    return str(tmp_path / "state.json")


@pytest.fixture
def persistence(storage_path: str) -> StatePersistence:
    """Хранилище состояний во временном файле."""
    return StatePersistence(storage_path)


@pytest.fixture
def engine(persistence: StatePersistence) -> FSMEngine:
    """Движок состояний с подключённым хранилищем."""
    return FSMEngine(event_bus=EventBus(), persistence=persistence)


def make_definition() -> FSMDefinition:
    """Собрать описание автомата освещения кухни.

    Returns:
        Описание автомата с двумя состояниями.
    """
    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="OFF",
        states=("OFF", "ON_MOTION"),
        transitions=(
            Transition(from_state="OFF", to_state="ON_MOTION", trigger="motion_detected"),
        ),
        target_device_id="light.kitchen",
    )


class TestStatePersistenceOnTransition:
    """Переход сохраняется в хранилище (FR-015)."""

    async def test_should_save_state_when_transition_occurs(
        self, engine: FSMEngine, persistence: StatePersistence
    ) -> None:
        """Выполненный переход сохраняет новое состояние."""
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")

        state = engine.get_state(FSM_ID)
        assert state is not None
        assert persistence.load_state(FSM_ID) == ("ON_MOTION", state.context)

    async def test_should_keep_last_state_when_transition_rejected(
        self, engine: FSMEngine, persistence: StatePersistence
    ) -> None:
        """Отклонённый переход не меняет сохранённое состояние."""
        engine.register_definition(make_definition())
        await engine.trigger(FSM_ID, "motion_detected")

        await engine.trigger(FSM_ID, "unknown_event")

        saved = persistence.load_state(FSM_ID)
        assert saved is not None
        assert saved[0] == "ON_MOTION"


class TestStateRestoration:
    """Состояние восстанавливается при регистрации определения (SC-016)."""

    async def test_should_restore_saved_state_when_engine_restarts(
        self, persistence: StatePersistence, storage_path: str
    ) -> None:
        """После перезапуска движка состояние отличается от начального."""
        first = FSMEngine(event_bus=EventBus(), persistence=StatePersistence(storage_path))
        first.register_definition(make_definition())
        await first.trigger(FSM_ID, "motion_detected")

        restarted = FSMEngine(event_bus=EventBus(), persistence=StatePersistence(storage_path))
        restarted.register_definition(make_definition())

        state = restarted.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "ON_MOTION"

    def test_should_use_initial_state_when_nothing_saved(
        self, persistence: StatePersistence
    ) -> None:
        """Без сохранённого состояния автомат стартует в начальном."""
        engine = FSMEngine(event_bus=EventBus(), persistence=persistence)

        engine.register_definition(make_definition())

        state = engine.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "OFF"

    def test_should_not_restore_state_outside_allowed_states(
        self, persistence: StatePersistence
    ) -> None:
        """Сохранённое состояние вне списка допустимых игнорируется."""
        persistence.save_state(FSM_ID, "НЕИЗВЕСТНОЕ_СОСТОЯНИЕ", {})
        engine = FSMEngine(event_bus=EventBus(), persistence=persistence)

        engine.register_definition(make_definition())

        state = engine.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "OFF"

    def test_should_not_restore_unregistered_fsm_after_restart(
        self, persistence: StatePersistence
    ) -> None:
        """Снятый с регистрации автомат не восстанавливается (SC-017)."""
        persistence.save_state("light.removed_lighting_10", "ON_MOTION", {})
        engine = FSMEngine(event_bus=EventBus(), persistence=persistence)

        engine.register_definition(make_definition())

        assert engine.get_state("light.removed_lighting_10") is None

    def test_should_skip_restoration_when_disabled(self, persistence: StatePersistence) -> None:
        """Явный запрет восстановления оставляет автомат в начальном состоянии."""
        persistence.save_state(FSM_ID, "ON_MOTION", {})
        engine = FSMEngine(event_bus=EventBus(), persistence=persistence)

        engine.register_definition(make_definition(), restore_state=False)

        state = engine.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "OFF"


class TestStorageLocation:
    """Файл состояний находится в каталоге данных платформы (T013)."""

    def test_should_default_to_data_directory_when_not_configured(self) -> None:
        """Путь по умолчанию — data/state.json, а не текущий каталог."""
        persistence = StatePersistence()

        assert persistence.storage_path == Path("data") / "state.json"

    async def test_should_write_file_inside_given_directory(
        self, tmp_path: Path, storage_path: str
    ) -> None:
        """Файл состояний создаётся в переданном каталоге, а не в домашнем."""
        engine = FSMEngine(event_bus=EventBus(), persistence=StatePersistence(storage_path))
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")

        assert Path(storage_path).exists()
        assert Path(storage_path).parent == tmp_path

    async def test_should_not_write_to_home_directory_when_transition_occurs(
        self, storage_path: str
    ) -> None:
        """Прежний путь ~/.homeassistant/.storage/fsm_persistence не используется."""
        engine = FSMEngine(event_bus=EventBus(), persistence=StatePersistence(storage_path))
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")

        legacy_path = (
            Path.home()
            / ".homeassistant"
            / ".storage"
            / "fsm_persistence"
            / "light_kitchen_lighting_10_mode.json"
        )
        assert not legacy_path.exists()


class TestPersistenceUnavailable:
    """Отсутствие хранилища не ломает работу движка (FR-016)."""

    async def test_should_work_without_persistence_when_not_configured(self) -> None:
        """Движок без хранилища выполняет переходы и не падает."""
        engine = FSMEngine(event_bus=EventBus())

        engine.register_definition(make_definition())

        assert await engine.trigger(FSM_ID, "motion_detected") is True

    async def test_should_restore_state_only_when_persistence_connected(
        self, storage_path: str
    ) -> None:
        """Без подключённого хранилища состояние не восстанавливается."""
        first = FSMEngine(event_bus=EventBus(), persistence=StatePersistence(storage_path))
        first.register_definition(make_definition())
        await first.trigger(FSM_ID, "motion_detected")

        without_storage = FSMEngine(event_bus=EventBus())
        without_storage.register_definition(make_definition())

        state: Any = without_storage.get_state(FSM_ID)
        assert state is not None
        assert state.current_state == "OFF"
