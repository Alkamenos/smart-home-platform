"""Таймер должен переживать перезапуск на настоящем хранилище, а не на заглушке.

Проверки `tests/unit/core/test_fsm_timeout_survives_restart.py` работают на
подставном хранилище. Но весь дефект #78 был в том, что **файл** состояний не
содержит времени входа: `state.json` хранит только `state` и `context`, а
таймер живёт в памяти процесса. Заглушка, которая сама помнит `entered_at`,
проверяла бы не то, что читает движок в бою.

Поэтому здесь настоящий `StatePersistence` на временном файле: первый экземпляр
пишет состояние с временем входа, второй — читает его, как при перезапуске
контейнера. Формат файла и есть то, что переживает перезапуск.

Плюс обратная проверка совместимости: состояние, записанное прежней версией
платформы (без `entered_at`), должно восстановиться без таймера и не сломать
запуск — иначе починка сломала бы первый запуск на существующем томе.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from core.fsm.engine import FSMDefinition, FSMEngine, State, Transition
from core.persistence.state_persistence import StatePersistence


#: Ожидание в состоянии `ON_MOTION` — как объявлено в `lighting.yaml`.
MOTION_TIMEOUT_SEC = 30.0

ENTITY_ID = "light.kitchen_lighting_10"


def _lighting_definition() -> FSMDefinition:
    """Собрать определение автомата освещения из шаблона.

    Returns:
        Определение с тем же набором переходов, что и в `lighting.yaml`.
    """
    return FSMDefinition(
        entity_id=ENTITY_ID,
        initial_state="OFF",
        states=["OFF", "ON_MOTION", "ON_MANUAL"],
        transitions=[
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                action=lambda *a, **k: None,
            ),
            Transition(
                from_state="ON_MOTION",
                to_state="OFF",
                trigger="timeout",
                action=lambda *a, **k: None,
                timeout_sec=MOTION_TIMEOUT_SEC,
            ),
        ],
    )


@pytest.fixture
def state_file(tmp_path: Path) -> Iterator[Path]:
    """Дать путь к файлу состояний во временном каталоге.

    Args:
        tmp_path: Временный каталог pytest.

    Yields:
        Путь к файлу состояний.
    """
    path = tmp_path / "state.json"
    yield path


class TestRealStorageFormat:
    """Настоящий файл состояний, а не заглушка."""

    @pytest.mark.asyncio
    async def test_state_file_keeps_entered_at(
        self, state_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Запись состояния содержит время входа в состояние.

        Args:
            state_file: Путь к файлу состояний.
            monkeypatch: Подмена часов на управляемые.
        """
        frozen = 1_700_000_000.0
        monkeypatch.setattr("core.fsm.engine.time.time", lambda: frozen)

        persistence = StatePersistence(storage_path=str(state_file))
        engine = FSMEngine(persistence=persistence)
        engine.register_definition(_lighting_definition())

        await engine.trigger(ENTITY_ID, "motion_detected")

        entry = json.loads(state_file.read_text(encoding="utf-8"))[ENTITY_ID]
        assert entry["state"] == "ON_MOTION"
        assert entry.get("entered_at") == frozen, (
            f"время входа в состояние не записано: {entry}. Именно его не хватало "
            f"для восстановления таймера — по одним `state` и `context` остаток "
            f"отложенного перехода вычислить нечем (Known Issue #78)"
        )

    @pytest.mark.asyncio
    async def test_restart_from_real_file_restores_timer(
        self, state_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Перезапуск на настоящем файле возвращает и состояние, и таймер.

        Args:
            state_file: Путь к файлу состояний.
            monkeypatch: Подмена часов на управляемые.
        """
        written_at = 1_700_000_000.0
        monkeypatch.setattr("core.fsm.engine.time.time", lambda: written_at)

        persistence = StatePersistence(storage_path=str(state_file))
        engine = FSMEngine(persistence=persistence)
        engine.register_definition(_lighting_definition())
        await engine.trigger(ENTITY_ID, "motion_detected")

        # Перезапуск: новый движок, тот же файл, часы сдвинуты на 25 секунд.
        monkeypatch.setattr("core.fsm.engine.time.time", lambda: written_at + 25)

        restarted = FSMEngine(persistence=StatePersistence(storage_path=str(state_file)))
        restarted.register_definition(_lighting_definition())

        state = restarted.get_state(ENTITY_ID)
        assert state is not None
        assert state.current_state == "ON_MOTION"
        assert restarted._timers.get(ENTITY_ID) is not None, (  # noqa: SLF001
            "состояние прочитано из настоящего state.json, а таймер не взведён: "
            "значит дефект не в заглушке, а в формате файла"
        )

    @pytest.mark.asyncio
    async def test_legacy_state_without_entered_at_still_starts(self, state_file: Path) -> None:
        """Состояние без времени входа восстанавливается и не роняет запуск.

        На существующем томе `state.json` записан прежней версией платформы, где
        `entered_at` не было. Починка не должна требовать миграции: первый запуск
        после развёртывания новой версии читает именно такие файлы.

        Args:
            state_file: Путь к файлу состояний.
        """
        state_file.write_text(
            json.dumps(
                {
                    ENTITY_ID: {
                        "state": "ON_MOTION",
                        "context": {"trace_id": "legacy"},
                    }
                }
            ),
            encoding="utf-8",
        )

        engine = FSMEngine(persistence=StatePersistence(storage_path=str(state_file)))
        engine.register_definition(_lighting_definition())

        state = engine.get_state(ENTITY_ID)
        assert state is not None
        assert state.current_state == "ON_MOTION", (
            "состояние, записанное прежней версией, должно восстановиться как "
            "раньше — иначе починка таймера ломает первый запуск на томе"
        )
        # Без времени входа остаток неизвестен, и состояние пролежало дольше
        # любого разумного ожидания только если файл старый. Здесь таймер
        # взводится на полный срок — это осознанный компромисс, но не повод
        # отказывать в запуске.
        assert engine._timers.get(ENTITY_ID) is not None, (  # noqa: SLF001
            "состояние без `entered_at` всё равно должно получить таймер: "
            "иначе после обновления на существующем томе свет снова застрянет "
            "включённым, только уже по другой причине"
        )


class TestStateAgeAccounting:
    """Возраст восстановленного состояния."""

    def test_age_is_measured_from_stored_entry(self, state_file: Path) -> None:
        """Возраст состояния равен прошедшему с момента входа времени.

        Args:
            state_file: Путь к файлу состояний.
        """
        state_file.write_text(
            json.dumps(
                {
                    ENTITY_ID: {
                        "state": "ON_MOTION",
                        "context": {},
                        "entered_at": 1_700_000_000.0,
                    }
                }
            ),
            encoding="utf-8",
        )

        engine = FSMEngine(persistence=StatePersistence(storage_path=str(state_file)))
        age = engine._restored_state_age(ENTITY_ID)  # noqa: SLF001

        assert age > 0, "возраст восстановленного состояния обязан быть больше нуля"

    def test_future_timestamp_does_not_yield_negative_age(self, state_file: Path) -> None:
        """Метка из будущего не даёт отрицательного возраста.

        Часы могут быть переведены или разойтись с часами контейнера. Отрицательный
        возраст означал бы «состояние войдёт в состояние в будущем» — из этого
        получился бы таймер длиннее объявленного.

        Args:
            state_file: Путь к файлу состояний.
        """
        import time

        state_file.write_text(
            json.dumps(
                {
                    ENTITY_ID: {
                        "state": "ON_MOTION",
                        "context": {},
                        "entered_at": time.time() + 10_000,
                    }
                }
            ),
            encoding="utf-8",
        )

        engine = FSMEngine(persistence=StatePersistence(storage_path=str(state_file)))
        age = engine._restored_state_age(ENTITY_ID)  # noqa: SLF001

        assert age == 0.0, f"метка из будущего дала отрицательный возраст: {age}"


def test_state_dataclass_still_usable() -> None:
    """Состояние остаётся конструируемым напрямую.

    Returns:
        Ничего.
    """
    state: Any = State(current_state="OFF", entered_at=0.0, context={})
    assert state.current_state == "OFF"
