"""Ночью движение не должно включать свет — и «ночь» должна считаться в часах дома.

Проверено на живом HA 2026-10-08: платформа живёт в часовом поясе UTC, дом — в
`Asia/Yekaterinburg` (UTC+5), а условие «сейчас день» считалось по часам
контейнера. Окно `07:00-23:00` в UTC открывалось с **02:00 до 04:00 по
местному** — то есть ровно тогда, когда яркий свет включать нельзя. В доме это
и есть «свет включился посреди ночи», и без часового пояса никакие ночные
правила не защищают.

Здесь проверяется условие «можно ли включать»:

- в окне тишины `quiet_from`–`quiet_to` движение не включает свет;
- исключение — комнаты из `night_motion_rooms` (санузел, кухня, коридор):
  встать за водой ночью должно быть можно;
- часы считаются в часовом поясе дома, а не контейнера;
- без настройки поведение консервативное: ночью не включаем.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.guards import builtin
from core.guards.builtin import (
    HOUSE_TZ,
    make_is_day_time,
    make_may_turn_on,
)


#: Часовой пояс дома: UTC+5 без перехода на летнее время.
HOUSE = ZoneInfo("Asia/Yekaterinburg")

#: Комната, которой ночью можно.
NIGHT_ROOM = "sanuzel"

#: Комната, которой ночью нельзя.
DAY_ROOM = "spalnia"


def _at(moment: datetime) -> Any:
    """Условие «можно ли включать» с часами, зафиксированными на момент.

    Args:
        moment: Момент, который для условия является «сейчас».

    Returns:
        Функция условия.
    """
    return make_may_turn_on(now=lambda _tz: moment)


def _ctx(room: str, **params: Any) -> dict[str, Any]:
    """Контекст перехода: комната, темнота и параметры поведения.

    По умолчанию ``daylight=False`` — проверки этого файла про ночное окно, а не
    про солнце: без состояния солнца условие в дневное время отвечает «нельзя»
    и проверки окон не проходят. Про солнце отдельно — ``test_motion_needs_darkness``.

    Args:
        room: Идентификатор комнаты.
        **params: Параметры поведения (окно тишины, ночные комнаты, пояс).

    Returns:
        Контекст для условия.
    """
    params.setdefault("daylight", False)
    return {"room": room, **params}


class TestQuietHours:
    """Окно тишины не даёт включить свет по движению."""

    def test_denies_inside_quiet_hours(self) -> None:
        """В 23:30 движение не включает свет."""
        guard = _at(datetime(2026, 10, 8, 23, 30, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM)) is False, (
            "в окне тишины движение включило свет в спальне: ночью яркий свет "
            "не нужен, и это ровно тот случай, который нельзя пропустить"
        )

    def test_allows_outside_quiet_hours(self) -> None:
        """Днём движение включает свет как обычно."""
        guard = _at(datetime(2026, 10, 8, 12, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM)) is True

    def test_allows_night_room_inside_quiet_hours(self) -> None:
        """В санузле ночью свет включить можно."""
        guard = _at(datetime(2026, 10, 8, 23, 30, tzinfo=HOUSE))

        assert guard(None, _ctx(NIGHT_ROOM, night_motion_rooms=[NIGHT_ROOM])) is True, (
            "санузел входит в список комнат, где ночью можно включить свет"
        )

    def test_other_rooms_stay_denied_when_list_is_set(self) -> None:
        """Список ночных комнат не превращается в «разрешено всем»."""
        guard = _at(datetime(2026, 10, 8, 2, 0, tzinfo=HOUSE))

        assert guard(None, _ctx("gostinaia", night_motion_rooms=[NIGHT_ROOM])) is False

    def test_window_crosses_midnight(self) -> None:
        """Окно через полночь считается двумя частями, а не переворачивается."""
        before = _at(datetime(2026, 10, 8, 22, 59, tzinfo=HOUSE))
        after = _at(datetime(2026, 10, 9, 0, 1, tzinfo=HOUSE))

        assert before(None, _ctx(DAY_ROOM)) is True
        assert after(None, _ctx(DAY_ROOM)) is False

    def test_quiet_window_from_manifest(self) -> None:
        """Окно и список комнат берутся из параметров поведения."""
        guard = _at(datetime(2026, 10, 8, 22, 0, tzinfo=HOUSE))
        params = {"quiet_from": "21:30", "quiet_to": "08:00", "night_motion_rooms": [NIGHT_ROOM]}

        assert guard(None, _ctx(DAY_ROOM, **params)) is False, (
            "окно из манифеста 21:30–08:00 не применилось: в 22:00 движение должно быть запрещено"
        )
        assert guard(None, _ctx(NIGHT_ROOM, **params)) is True

    def test_without_configuration_night_is_denied(self) -> None:
        """Без настроек поведение консервативное: ночью не включаем."""
        guard = _at(datetime(2026, 10, 8, 3, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM)) is False

    def test_unreadable_window_denies(self) -> None:
        """Неразобранное окно ведёт к отказу, а не к «включай всегда»."""
        guard = _at(datetime(2026, 10, 8, 12, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, quiet_from="полночь")) is False


class TestHouseTimezone:
    """Ночь считается в часах дома, а не контейнера."""

    def test_night_is_detected_by_house_clock(self) -> None:
        """02:00 по местному — ночь, даже если в UTC это 21:00 предыдущего дня."""
        moment = datetime(2026, 10, 8, 21, 0, tzinfo=ZoneInfo("UTC")).astimezone(HOUSE)
        guard = _at(moment)

        assert guard(None, _ctx(DAY_ROOM, time_zone="Asia/Yekaterinburg")) is False, (
            f"время дома {moment.isoformat()} отнесено к дню: окно тишины "
            "считается не в тех часах, и ночью включится свет"
        )

    def test_is_day_time_also_uses_house_clock(self) -> None:
        """Старое правило «сейчас день» не должно считать ночь днём."""
        moment = datetime(2026, 10, 8, 21, 0, tzinfo=ZoneInfo("UTC")).astimezone(HOUSE)
        day_guard = make_is_day_time("07:00-23:00", now=lambda: moment)

        assert day_guard(None, {}) is False, (
            "is_day_time посчитал 02:00 по местному днём, значит часовой пояс "
            "условия расходится с часовым поясом дома — это и было причиной "
            "ночных включений в живом запуске"
        )

    def test_is_day_time_without_override_uses_house_timezone(self) -> None:
        """Без подмены часов `is_day_time` берёт время дома, а не UTC.

        Returns:
            Ничего.
        """
        guard = make_is_day_time("00:00-23:59")

        assert guard(None, {}) is True, "условие дня должно работать без подмены времени"

    def test_timezone_from_environment(self) -> None:
        """Часовой пояс дома задаётся переменной, а не угадывается.

        Returns:
            Ничего.
        """
        monkey = pytest.MonkeyPatch()
        monkey.setenv("HOUSE_TIMEZONE", "Asia/Yekaterinburg")
        try:
            assert builtin._resolve_house_tz() == ZoneInfo("Asia/Yekaterinburg")
        finally:
            monkey.undo()

    def test_unknown_timezone_falls_back(self) -> None:
        """Неизвестный пояс не ломает работу: берётся следующий источник.

        Returns:
            Ничего.
        """
        monkey = pytest.MonkeyPatch()
        monkey.setenv("HOUSE_TIMEZONE", "Not/AZone")
        monkey.setenv("TZ", "Not/AZone")
        try:
            assert builtin._resolve_house_tz() is not None
        finally:
            monkey.undo()

    def test_default_timezone_is_available(self) -> None:
        """Даже без переменных условия получают часовой пояс.

        Returns:
            Ничего.
        """
        assert HOUSE_TZ is not None


class TestGuardIsRegistered:
    """Новое условие доступно шаблонам под своим именем."""

    def test_may_turn_on_is_registered(self) -> None:
        """Реестр отдаёт условие, которое зовёт шаблон света."""
        from core.control_tracker import ControlTracker
        from core.guards.builtin import REGISTERED_GUARDS, register_all_guards
        from core.registry import Registry

        registry = Registry()
        register_all_guards(registry, ControlTracker())

        assert "may_turn_on" in REGISTERED_GUARDS
        assert registry.get_guard("may_turn_on") is not None


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 15, False),  # после полуночи — ночь
        (6, 15, False),  # 06:15 — ещё тишина
        (6, 45, True),  # 06:45 — уже день
        (13, 45, True),  # день
        (22, 45, True),  # 22:45 — до тишины 15 минут
        (23, 15, False),  # тишина началась
    ],
)
def test_day_boundary(hour: int, minute: int, expected: bool) -> None:
    """Границы окна тишины считаются по часам дома.

    Args:
        hour: Час в местном времени.
        minute: Минута в местном времени.
        expected: Ожидаемое решение условия.
    """
    guard = _at(datetime(2026, 10, 8, hour, minute, tzinfo=HOUSE))

    assert guard(None, _ctx(DAY_ROOM)) is expected


class TestHouseRulesReachTheGuard:
    """Правила из манифеста доходят до условия через параметры поведения."""

    def test_behavior_gets_quiet_hours_and_room(self) -> None:
        """Устройство получает окно тишины и свою комнату."""
        from core.control_tracker import ControlTracker
        from core.fsm.engine import FSMEngine
        from core.fsm.factory import FSMFactory
        from core.guards.builtin import register_all_guards
        from core.models.manifest import (
            AutomationDomainRules,
            AutomationRules,
            BehaviorConfig,
            DeviceConfig,
            InstanceConfig,
            Manifest,
            RoomConfig,
        )
        from core.registry import Registry

        registry = Registry()
        register_all_guards(registry, ControlTracker())
        engine = FSMEngine()
        manifest = Manifest(
            version=1,
            instance=InstanceConfig(
                id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
            ),
            rooms=[
                RoomConfig(
                    id="sanuzel",
                    name="Санузел",
                    sensors={"motion": "binary_sensor.probe"},
                    devices=[
                        DeviceConfig(
                            id="light.probe",
                            type="light",
                            behaviors=[BehaviorConfig(template="lighting", priority=10, params={})],
                        )
                    ],
                )
            ],
            automation_rules=AutomationRules(
                time_zone="Asia/Yekaterinburg",
                lighting=AutomationDomainRules(
                    quiet_from="23:00", quiet_to="06:30", night_motion_rooms=["sanuzel"]
                ),
            ),
        )
        FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)

        # Описания автоматов публично не отдаются: проверка идёт через внутреннее
        # хранилище движка — так же, как это делают проверки роутера и клиента.
        definition = engine._definitions.get("light.probe_lighting_10")  # noqa: SLF001
        assert definition is not None, "автомат не создан"
        assert definition.room == "sanuzel", (
            f"комната не попала в описание автомата: {definition.room!r} — ночное "
            "правило не сможет отличить санузел от спальни"
        )
        assert definition.params["quiet_from"] == "23:00", (
            f"окно тишины не дошло до поведения: {definition.params}"
        )
        assert definition.params["night_motion_rooms"] == ["sanuzel"]
        assert definition.params["time_zone"] == "Asia/Yekaterinburg"

    def test_explicit_behavior_param_wins(self) -> None:
        """Параметр устройства главнее правила дома."""
        from core.fsm.factory import FSMFactory
        from core.models.manifest import AutomationDomainRules, AutomationRules, BehaviorConfig

        factory = FSMFactory(engine=None, registry=None, event_bus=None)  # type: ignore[arg-type]
        behavior = BehaviorConfig(template="lighting", priority=10, params={"quiet_from": "20:00"})
        rules = AutomationRules(lighting=AutomationDomainRules(quiet_from="23:00"))

        merged = factory._with_house_rules(behavior, rules)

        assert merged.params["quiet_from"] == "20:00", (
            "правило дома перезаписало явный параметр устройства: настройка "
            "конкретного светильника должна быть главнее"
        )


class TestNightDenialIsNamed:
    """Ночной отказ называет себя, чтобы журнал был понятен без догадок."""

    def test_quiet_hours_named_in_the_morning(self) -> None:
        """Днём условие разрешает, и отказ не выдумывается.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 8, 12, 0, tzinfo=HOUSE))

        assert guard.deny_reason(None, _ctx(DAY_ROOM)) is None  # type: ignore[attr-defined]

    def test_quiet_hours_named_at_night(self) -> None:
        """Ночью отказ называется ночным окном."""
        guard = _at(datetime(2026, 10, 8, 23, 30, tzinfo=HOUSE))

        assert guard.deny_reason(None, _ctx(DAY_ROOM)) == "quiet_hours"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_engine_records_quiet_hours_reason(self) -> None:
        """Движок записывает названную условием причину, а не общую."""
        from core.action_handlers import register_all_actions
        from core.control_tracker import ControlTracker
        from core.events.fsm_events import REASON_QUIET_HOURS
        from core.fsm.engine import FSMEngine
        from core.fsm.factory import FSMFactory
        from core.guards.builtin import register_all_guards
        from core.models.manifest import (
            BehaviorConfig,
            DeviceConfig,
            InstanceConfig,
            Manifest,
            RoomConfig,
        )
        from core.registry import Registry

        night = datetime(2026, 10, 8, 23, 30, tzinfo=HOUSE)
        registry = Registry()
        register_all_actions(registry)
        register_all_guards(registry, ControlTracker())
        # Часы подменяются ДО сборки автомата: фабрика берёт условие из реестра
        # один раз и вставляет вызов в переход, поэтому подмена после сборки
        # осталась бы незамеченной — ровно так проверка и врала бы.
        registry.register_guard("may_turn_on", make_may_turn_on(now=lambda _tz: night))

        engine = FSMEngine()
        manifest = Manifest(
            version=1,
            instance=InstanceConfig(
                id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
            ),
            rooms=[
                RoomConfig(
                    id="spalnia",
                    name="Спальня",
                    sensors={"motion": "binary_sensor.probe"},
                    devices=[
                        DeviceConfig(
                            id="light.probe",
                            type="light",
                            behaviors=[BehaviorConfig(template="lighting", priority=10, params={})],
                        )
                    ],
                )
            ],
        )
        FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)

        await engine.trigger(
            "light.probe_lighting_10", "motion_detected", {"motion": True, "room": "spalnia"}
        )

        assert engine.rejection_counts().get(REASON_QUIET_HOURS) == 1, (
            f"ночной отказ не назван ночным окном: {engine.rejection_counts()}. По "
            "журналу нельзя отличить тихое время от молчащего датчика"
        )
