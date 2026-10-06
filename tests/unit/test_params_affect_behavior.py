"""Параметры поведения влияют на поведение, а не лежат в описании (#71).

Три параметра из вашего манифеста развёртывания не влияли ни на что:
`motion_timeout_sec` (таймаут брался из YAML), `target_temp` и `hysteresis`
(не читались в горячем пути). Первые два правятся здесь, третий требует правки
имён событий и guard'ов в `climate_control.yaml` и остаётся отдельной задачей —
здесь это зафиксировано тестом, чтобы «осталось» не превратилось в «считается
сделанным».

Проверки бьют по результату: значение таймаура берётся из созданного перехода, а
не из промежуточных переменных фабрики.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

import yaml

from core.action_handlers import climate_cool, climate_heat, register_all_actions
from core.control_tracker import ControlTracker
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.guards.builtin import register_all_guards
from core.registry import Registry


def _factory() -> FSMFactory:
    """Фабрика с реестром действий и guard'ов.

    Без guard'ов фабрика отбрасывает поведение целиком: переходы с неизвестным
    guard'ом считаются некорректными, и  возвращает пустой
    список. Первая редакция проверки регистрировала только действия — падало с
    IndexError, и причина была не в таймауте.

    Returns:
        Экземпляр фабрики.
    """
    registry = Registry()
    register_all_actions(registry)
    register_all_guards(registry, ControlTracker())
    return FSMFactory(engine=FSMEngine(), registry=registry, event_bus=None)


def _timeout_for(definition: Any, from_state: str, trigger: str) -> float | None:
    """Возвращает таймаут перехода по состоянию и триггеру.

    Args:
        definition: Созранённое описание автомата.
        from_state: Состояние, из которого ведёт переход.
        trigger: Триггер перехода.

    Returns:
        Значение таймаута либо None.
    """
    for transition in definition.transitions:
        if transition.from_state == from_state and transition.trigger == trigger:
            return transition.timeout_sec
    raise AssertionError(
        f"в переходах нет {from_state} --[{trigger}]-->, есть: "
        f"{[(t.from_state, t.trigger) for t in definition.transitions]}"
    )


class TestMotionTimeoutFromParams:
    """`motion_timeout_sec` задаёт таймаут перехода."""

    def test_should_use_param_instead_of_yaml_value(self) -> None:
        """Значение параметра выигрывает у значения в шаблоне."""
        definition = _factory().create_from_manifest(_manifest_with_timeout(180))

        assert _timeout_for(definition[0], "ON_MOTION", "timeout") == 180, (
            "таймаут по-прежнему берётся из YAML: параметр поведения, который "
            "пользователь задаёт в манифесте, не имеет силы (#71)"
        )

    def test_should_fall_back_to_yaml_when_param_absent(self) -> None:
        """Без параметра действует значение шаблона.

        Отдельная проверка: иначе «параметр работает» будет означать, что
        значение шаблона перестало работать вовсе.
        """
        definition = _factory().create_from_manifest(_manifest_with_timeout(None))

        assert _timeout_for(definition[0], "ON_MOTION", "timeout") == 30.0, (
            "значение шаблона должно сохраняться"
        )


class TestClimateTargetTemperature:
    """`target_temp` доходит до команды HA."""

    def test_should_send_target_temp_from_manifest_params(self) -> None:
        """Параметр из манифеста попадает в команду.

        Имя параметра в манифесте — `target_temp`, а действие читало
        `target_temperature`. Расхождение имён и было причиной: параметр был
        задан, команда уходила без температуры.
        """
        intent = climate_heat(None, {"entity_id": "climate.living", "target_temp": 22.5})

        assert intent is not None
        assert intent.data["temperature"] == 22.5, (
            "целевая температура не ушла в команду: параметр объявлен в "
            "манифесте, но действие читало другое имя"
        )

    def test_should_keep_working_without_target_temp(self) -> None:
        """Без параметра команда всё равно отправляется, как раньше.

        Args:
            Пустой контекст: устройство есть, температуры нет.
        """
        intent = climate_heat(None, {"entity_id": "climate.living"})

        assert intent is not None
        assert "temperature" not in intent.data

    def test_should_apply_to_cooling_as_well(self) -> None:
        """Охлаждение использует тот же параметр.

        Args:
            Пустой контекст: устройство есть.
        """
        intent = climate_cool(None, {"entity_id": "climate.living", "target_temp": 24.0})

        assert intent is not None
        assert intent.data["temperature"] == 24.0


class TestHysteresisStillNotEffective:
    """`hysteresis` остаётся нерабочим, и это зафиксировано."""

    def test_should_not_promise_hysteresis_in_manifest_params(self) -> None:
        """Контракт не должен обещать работающий `hysteresis`.

        Сделать его действующим можно только вместе с правкой имён событий
        (`temperature_low` → `temperature_changed`) и guard'ами по
        температуре: без них климат не срабатывает вовсе, и параметру не на чем
        действовать. Пока это не сделано, метка `effective: false` обязана стоять.
        """
        contract = yaml.safe_load(
            (_repo_root() / "src" / "features" / "CONTRACT.yaml").read_text(encoding="utf-8")
        )
        hysteresis = contract["templates"]["climate_control"]["params"]["hysteresis"]

        assert hysteresis["effective"] is False
        assert "ИНЕРТЕН" in hysteresis["note"]


def _repo_root() -> Any:
    """Возвращает корень репозитория.

    Returns:
        Путь к корню.
    """
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


def _manifest_with_timeout(motion_timeout: int | None) -> Any:
    """Собирает манифест с одним устройством и заданным таймаутом.

    Args:
        motion_timeout: Значение параметра либо None, чтобы его не задавать.

    Returns:
        Модель манифеста.
    """
    from core.models.manifest import (
        AutomationRules,
        BehaviorConfig,
        DeviceConfig,
        InstanceConfig,
        Manifest,
        RoomConfig,
    )

    params: dict[str, Any] = {}
    if motion_timeout is not None:
        params["motion_timeout_sec"] = motion_timeout

    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="test-house",
            name="Test House",
            owner="test-owner",
            created_at="2026-01-01T00:00:00Z",
        ),
        rooms=[
            RoomConfig(
                id="kitchen",
                name="Kitchen",
                sensors={"motion": "binary_sensor.probe"},
                devices=[
                    DeviceConfig(
                        id="light.probe",
                        type="light",
                        behaviors=[BehaviorConfig(template="lighting", priority=10, params=params)],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )
