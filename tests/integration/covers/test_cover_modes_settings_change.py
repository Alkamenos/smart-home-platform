"""Шторы открываются и закрываются по флагам дома — сквозная проверка (спека 015).

Проверка идёт на настоящих объектах движка, роутера и фабрики: ``EventRouter``
доносит смену флагов дома событием ``settings_changed`` (``route_settings_change``),
условия ``covers_should_open``/``covers_should_close`` решают, а действия
``cover_open``/``cover_close`` создают команды, которые получает диспетчер.

Сценарии — правила владельца (spec.md, FR-002…FR-007): спим и разрешено закрывать,
спим без разрешения, штора над дверью при людях, никого нет, дома только собаки,
аварийный флаг.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


PRIORITY = 10
SPALNIA = "cover.shtora_v_spalne"
KABINET = "cover.shtora_v_kabinete"
GOSTINNAIA_LEFT = "cover.shtora_v_gostinnoi_levaia"
GOSTINNAIA_DOOR = "cover.shtora_v_gostinnoi_pravaia"

SPALNIA_FSM = f"{SPALNIA}_cover_modes_{PRIORITY}"
DOOR_FSM = f"{GOSTINNAIA_DOOR}_cover_modes_{PRIORITY}"
LEFT_FSM = f"{GOSTINNAIA_LEFT}_cover_modes_{PRIORITY}"

#: Флаги, как их читает платформа из Home Assistant (контекст события).
_BASE = {
    "covers_enabled": True,
    "my_doma": True,
    "sobaki_doma": True,
    "cover_emergency": False,
    "sleep_modifier_on": False,
    "covers_close_night": True,
}


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в HA."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True

    def by_device(self, device_id: str) -> list[str]:
        """Сервисы команд конкретной шторы.

        Args:
            device_id: Сущность шторы.

        Returns:
            Список имён сервисов по порядку.
        """
        return [i.service for i in self.intents if i.device_id == device_id]


def _manifest() -> Manifest:
    """Манифест: три шторы — спальня, левая гостиной и над дверью.

    Returns:
        Модель манифеста.
    """

    def room(room_id: str, name: str, devices: list[DeviceConfig]) -> RoomConfig:
        """Собрать комнату со шторами.

        Args:
            room_id: Идентификатор комнаты.
            name: Имя комнаты.
            devices: Устройства комнаты.

        Returns:
            Модель комнаты.
        """
        return RoomConfig(id=room_id, name=name, sensors={}, devices=devices)

    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            room(
                "spalnia",
                "Спальня",
                [
                    DeviceConfig(
                        id=SPALNIA,
                        type="cover",
                        behaviors=[
                            BehaviorConfig(
                                template="cover_modes",
                                priority=PRIORITY,
                                params={"closes_when_dogs_only": True},
                            )
                        ],
                    )
                ],
            ),
            room(
                "kabinet",
                "Кабинет",
                [
                    DeviceConfig(
                        id=KABINET,
                        type="cover",
                        behaviors=[
                            BehaviorConfig(
                                template="cover_modes",
                                priority=PRIORITY,
                                params={"closes_when_dogs_only": True},
                            )
                        ],
                    )
                ],
            ),
            room(
                "gostinaia",
                "Гостиная",
                [
                    DeviceConfig(
                        id=GOSTINNAIA_LEFT,
                        type="cover",
                        behaviors=[
                            BehaviorConfig(
                                template="cover_modes",
                                priority=PRIORITY,
                                params={},
                            )
                        ],
                    ),
                    DeviceConfig(
                        id=GOSTINNAIA_DOOR,
                        type="cover",
                        behaviors=[
                            BehaviorConfig(
                                template="cover_modes",
                                priority=PRIORITY,
                                params={"cover_role": "door"},
                            )
                        ],
                    ),
                ],
            ),
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер штор.

    Returns:
        Движок, роутер и помнящий команды диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.guards.builtin import register_all_guards

    manifest = _manifest()
    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


def _state(engine: FSMEngine, fsm: str) -> str:
    """Текущее состояние автомата.

    Args:
        engine: Движок с автоматами.
        fsm: Идентификатор автомата.

    Returns:
        Имя состояния.
    """
    state = engine.get_state(fsm)
    assert state is not None
    return state.current_state


class TestCoverModesFollowHomeFlags:
    """Шторы открываются и закрываются по флагам дома."""

    @pytest.mark.asyncio
    async def test_sleeping_closes_all_but_door(self) -> None:
        """Спим и разрешено закрывать ночью — закрываются все, кроме двери."""
        engine, router, dispatcher = _build()

        await router.route_settings_change({**_BASE, "sleep_modifier_on": True})

        assert _state(engine, SPALNIA_FSM) == "CLOSED"
        assert _state(engine, LEFT_FSM) == "CLOSED"
        assert _state(engine, DOOR_FSM) == "OPEN", (
            "штора над дверью закрылась при людях в доме — мешает выходу"
        )
        assert dispatcher.by_device(SPALNIA) == ["close_cover"]

    @pytest.mark.asyncio
    async def test_awake_opens_everything(self) -> None:
        """Не спим — шторы открыты."""
        engine, router, dispatcher = _build()

        await router.route_settings_change({**_BASE, "sleep_modifier_on": True})
        dispatcher.intents.clear()
        await router.route_settings_change({**_BASE, "sleep_modifier_on": False})

        assert _state(engine, SPALNIA_FSM) == "OPEN"
        assert dispatcher.by_device(SPALNIA) == ["open_cover"]

    @pytest.mark.asyncio
    async def test_sleeping_without_night_permission_stays_open(self) -> None:
        """Спим, но закрывать ночью не разрешено — шторы открыты."""
        engine, router, _ = _build()

        await router.route_settings_change(
            {**_BASE, "sleep_modifier_on": True, "covers_close_night": False}
        )

        assert _state(engine, SPALNIA_FSM) == "OPEN"
        assert _state(engine, DOOR_FSM) == "OPEN"

    @pytest.mark.asyncio
    async def test_nobody_home_closes_including_door(self) -> None:
        """Никого и собак нет — закрывается всё, включая дверь."""
        engine, router, dispatcher = _build()

        await router.route_settings_change(
            {**_BASE, "my_doma": False, "sobaki_doma": False, "sleep_modifier_on": False}
        )

        assert _state(engine, SPALNIA_FSM) == "CLOSED"
        assert _state(engine, LEFT_FSM) == "CLOSED"
        assert _state(engine, DOOR_FSM) == "CLOSED", "дома никого — штору над дверью можно закрыть"
        assert dispatcher.by_device(GOSTINNAIA_DOOR) == ["close_cover"]

    @pytest.mark.asyncio
    async def test_dogs_home_close_only_bedroom_and_study(self) -> None:
        """Дома только собаки — закрываются спальня и кабинет."""
        engine, router, _ = _build()

        await router.route_settings_change(
            {**_BASE, "my_doma": False, "sobaki_doma": True, "sleep_modifier_on": True}
        )

        assert _state(engine, SPALNIA_FSM) == "CLOSED"
        assert _state(engine, f"{KABINET}_cover_modes_{PRIORITY}") == "CLOSED"
        assert _state(engine, LEFT_FSM) == "OPEN", "чужая комната закрылась при собаках"
        assert _state(engine, DOOR_FSM) == "OPEN"

    @pytest.mark.asyncio
    async def test_emergency_opens_everything_even_with_feature_off(self) -> None:
        """Аварийный флаг открывает всё, игнорируя остальные правила."""
        engine, router, dispatcher = _build()

        # Сначала закрыть (никого нет), затем авария + выключенный фиче-флаг.
        await router.route_settings_change(
            {**_BASE, "my_doma": False, "sobaki_doma": False, "sleep_modifier_on": False}
        )
        assert _state(engine, SPALNIA_FSM) == "CLOSED"

        dispatcher.intents.clear()
        await router.route_settings_change(
            {
                **_BASE,
                "my_doma": False,
                "sobaki_doma": False,
                "cover_emergency": True,
                "covers_enabled": False,
            }
        )

        assert _state(engine, SPALNIA_FSM) == "OPEN"
        assert _state(engine, DOOR_FSM) == "OPEN"
        assert dispatcher.by_device(SPALNIA) == ["open_cover"]

    @pytest.mark.asyncio
    async def test_feature_off_leaves_covers_alone(self) -> None:
        """Фиче-флаг выключен — платформа шторы не трогает."""
        engine, router, dispatcher = _build()

        await router.route_settings_change(
            {**_BASE, "covers_enabled": False, "sleep_modifier_on": True}
        )

        assert _state(engine, SPALNIA_FSM) == "OPEN"
        assert dispatcher.intents == []
