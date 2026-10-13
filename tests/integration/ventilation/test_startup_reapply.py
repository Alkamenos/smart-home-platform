"""Восстановленное состояние переприменяется прибору при запуске (B43, спека 014).

Автомат хранит состояние между перезапусками: платформа запускается и
восстанавливает, скажем, «Приток MAX». Входа в это состояние не было, поэтому
команда прибору не уходила — рекуператор оставался в прежнем режиме, а после
потери питания и вовсе выключенным, хотя автомат считал себя в максимальном
притоке (боевая находка B43). При подключении адаптер шлёт один общий пересмотр
`settings_changed` с признаком `startup_reapply`, и шаблон вентиляции подтверждает
решение как обычный вход: включает прибор и задаёт режим.

Проверка идёт на настоящих объектах движка, роутера и фабрики, как в
``test_ventilation_settings_change.py``.

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


SENSOR = "sensor.datchik_temperatury_kabinet_temperature"
FAN = "fan.base_smart"
EXHAUST = "fan.vytyazhka_sanuzel"
ROOM = "kabinet"
PRIORITY = 10
FAN_FSM = f"{FAN}_ventilation_modes_{PRIORITY}"
EXHAUST_FSM = f"{EXHAUST}_ventilation_modes_{PRIORITY}"

SUPPLY_PARAMS: dict[str, Any] = {
    "ventilation_role": "supply",
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_airing": "Приток MAX",
    "speed_normal": 42,
    "speed_min": 14,
    "speed_cold_reference": 5.0,
    "speed_cold_gain": 2.0,
}

EXHAUST_PARAMS: dict[str, Any] = {
    "ventilation_role": "exhaust",
    "exhaust_temp_threshold": 25.0,
    "exhaust_humidity_threshold": 65.0,
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

    def services(self) -> list[str]:
        """Сервисы всех команд, что дошли до диспетчера.

        Returns:
            Список имён сервисов.
        """
        return [intent.service for intent in self.intents]

    def services_for(self, device_id: str) -> list[str]:
        """Сервисы команд конкретного прибора.

        В одной комнате два прибора вентиляции, и их команды идут в общий
        диспетчер: без фильтра чужая команда попадёт в проверку.

        Args:
            device_id: Идентификатор прибора.

        Returns:
            Список имён сервисов.
        """
        return [i.service for i in self.intents if i.device_id == device_id]


def _manifest() -> Manifest:
    """Манифест из одной комнаты: датчик, рекуператор и вытяжка.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=ROOM,
                name="Кабинет",
                sensors={"temperature": SENSOR},
                devices=[
                    DeviceConfig(
                        id=FAN,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="ventilation_modes",
                                priority=PRIORITY,
                                params=dict(SUPPLY_PARAMS),
                            )
                        ],
                    ),
                    DeviceConfig(
                        id=EXHAUST,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="ventilation_modes",
                                priority=PRIORITY,
                                params=dict(EXHAUST_PARAMS),
                            )
                        ],
                    ),
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер вентиляции.

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


def _restore(engine: FSMEngine, fsm: str, state: str) -> None:
    """Поставить автомат в состояние, как при восстановлении после запуска.

    Args:
        engine: Движок с автоматами.
        fsm: Идентификатор автомата.
        state: Восстановленное состояние.

    Returns:
        Ничего.
    """
    restored = engine.get_state(fsm)
    assert restored is not None
    restored.current_state = state


_STARTUP: dict[str, Any] = {
    "outside_temperature": 0.0,
    "is_winter": True,
    "ventilation_on": True,
    "_startup_reapply": True,
}


class TestStartupReapply:
    """Первый пересмотр после запуска подтверждает решение прибору."""

    @pytest.mark.asyncio
    async def test_restored_airing_powers_on_and_asserts_mode(self) -> None:
        """Восстановленный «Приток MAX» подтверждается как обычный вход.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        _restore(engine, FAN_FSM, "AIRING")

        await router.route_settings_change(dict(_STARTUP))

        assert dispatcher.services_for(FAN) == ["turn_on", "set_preset_mode"], (
            f"после запуска ушло {dispatcher.services_for(FAN)} вместо «включение, "
            "затем режим»: восстановленный автомат считал себя в «Притоке MAX», "
            "а прибор мог стоять (B43)"
        )
        fan_intents = [i for i in dispatcher.intents if i.device_id == FAN]
        assert fan_intents[0].data == {"percentage": 100}
        assert fan_intents[1].data["preset_mode"] == "Приток MAX"

    @pytest.mark.asyncio
    async def test_restored_exhaust_powers_on_when_needed(self) -> None:
        """Восстановленная вытяжка подтверждается, пока она нужна.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        _restore(engine, EXHAUST_FSM, "EXHAUST")

        await router.route_settings_change({**_STARTUP, "exhaust_on": True})

        assert "turn_on" in dispatcher.services_for(EXHAUST), (
            "восстановленная вытяжка не подтвердилась прибору: он мог остаться "
            "выключенным, хотя автомат считал себя в вытяжке (B43)"
        )

    @pytest.mark.asyncio
    async def test_flag_change_does_not_power_on_restored_airing(self) -> None:
        """Без признака запуска подтверждается только режим, без включения.

        Держит в узде лечение дрейфа: включение с процентом сбрасывает режим
        прибора, поэтому в обычном подтверждении его быть не должно.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        _restore(engine, FAN_FSM, "AIRING")

        context = {k: v for k, v in _STARTUP.items() if k != "_startup_reapply"}
        await router.route_settings_change({**context, "temperature": 28.0, "comfort_max": 25.0})

        assert dispatcher.services_for(FAN) == ["set_preset_mode"], (
            f"обычный пересмотр ушёл как {dispatcher.services_for(FAN)}: включение "
            "с процентом в подтверждении сбрасывает режим прибора"
        )

    @pytest.mark.asyncio
    async def test_stopped_device_is_powered_on(self) -> None:
        """Признак остановки прибора превращает подтверждение во вход (B54).

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        _restore(engine, FAN_FSM, "AIRING")

        await router.route_settings_change(
            {
                "outside_temperature": 0.0,
                "is_winter": True,
                "ventilation_on": True,
                "_device_is_off": True,
            }
        )

        assert dispatcher.services_for(FAN) == ["turn_on", "set_preset_mode"], (
            f"остановленному прибору ушло {dispatcher.services_for(FAN)}: "
            "подтверждение одним режимом не поднимет рекуператор"
        )
        fan_intents = [i for i in dispatcher.intents if i.device_id == FAN]
        assert fan_intents[1].data["preset_mode"] == "Приток MAX"

    @pytest.mark.asyncio
    async def test_startup_flag_does_not_survive_the_event(self) -> None:
        """Одноразовый признак запуска не переживает свой пересмотр (B43).

        Если он останется в накопленном контексте, следующее событие — тик
        сторожа — снова отправит включение с процентом и сбросит режим прибора
        (боевая находка 2026-10-13: признак всплыл через пять минут).

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()
        _restore(engine, FAN_FSM, "AIRING")

        await router.route_settings_change({**_STARTUP, "temperature": 28.0, "comfort_max": 25.0})
        assert dispatcher.services_for(FAN) == ["turn_on", "set_preset_mode"]
        dispatcher.intents.clear()

        # Следующий пересмотр — уже без признака запуска (как тик сторожа).
        context = {k: v for k, v in _STARTUP.items() if k != "_startup_reapply"}
        await router.route_settings_change({**context, "temperature": 28.0, "comfort_max": 25.0})

        assert dispatcher.services_for(FAN) == ["set_preset_mode"], (
            f"через пять минут ушло {dispatcher.services_for(FAN)}: одноразовый "
            "признак запуска пережил событие и снова включил прибор с процентом"
        )
