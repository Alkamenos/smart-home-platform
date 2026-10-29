"""Глобальная цветовая температура света: кривая и служба (задача B97).

Владелец хочет один общий свет: днём холодный, после заката плавно теплеет и к
21:00 становится максимально тёплым. Служба считает значение, пишет его в
helper Home Assistant и обновляет горящие лампы; при включении действие берёт
текущее значение из helper-а.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.models.manifest import (
    AutomationDomainRules,
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.services.light_color_temperature import (
    LightColorTemperatureService,
    _lighting_devices,
    target_kelvin,
)


TZ = ZoneInfo("Asia/Yekaterinburg")
NOW = datetime(2026, 10, 21, 19, 30, tzinfo=TZ)


def _manifest() -> Manifest:
    """Манифест: три лампы, из них глобальная температура нужна одной.

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
                id="gostinaia",
                name="Гостиная",
                devices=[
                    DeviceConfig(
                        id="light.table",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={
                                    "brightness_pct": 100,
                                    "use_global_color_temp": True,
                                },
                            )
                        ],
                    ),
                    DeviceConfig(
                        id="light.off",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={"use_global_color_temp": True},
                            )
                        ],
                    ),
                    DeviceConfig(
                        id="light.onoff",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={"use_global_color_temp": True},
                            )
                        ],
                    ),
                ],
            )
        ],
        automation_rules=AutomationRules(
            time_zone="Asia/Yekaterinburg",
            lighting=AutomationDomainRules(
                color_temp_day_entity="input_number.temperatura_sveta_dnem",
                color_temp_night_entity="input_number.temperatura_sveta_nochiu",
                color_temp_current_entity="input_number.tekushchaia_temperatura",
                color_temp_warm_at="21:00",
                color_temp_update_minutes=5,
            ),
        ),
    )


class _Adapter:
    """Адаптер-двойник: отдаёт заданные состояния и запоминает запись helper-а."""

    def __init__(
        self,
        states: dict[str, str],
        snapshots: dict[str, dict[str, Any]],
    ) -> None:
        self._states = states
        self._snapshots = snapshots
        self.calls: list[dict[str, Any]] = []

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Прочитать состояние.

        Args:
            entity_id: Сущность.

        Returns:
            Состояние либо None.
        """
        return self._states.get(entity_id)

    async def get_entity_snapshot(self, entity_id: str) -> dict[str, Any] | None:
        """Прочитать снимок.

        Args:
            entity_id: Сущность.

        Returns:
            Снимок либо None.
        """
        return self._snapshots.get(entity_id)

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> bool:
        """Запомнить вызов сервиса.

        Args:
            domain: Домен.
            service: Сервис.
            entity_id: Сущность.
            data: Данные.
            _kwargs: Прочие параметры.

        Returns:
            True.
        """
        self.calls.append(
            {
                "domain": domain,
                "service": service,
                "entity_id": entity_id,
                "data": dict(data or {}),
            }
        )
        return True


class _Dispatcher:
    """Диспетчер-двойник: запоминает намерения."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить намерение.

        Args:
            intent: Команда.

        Returns:
            True.
        """
        self.intents.append(intent)
        return True


def _adapter(current: str = "6000") -> _Adapter:
    """Адаптер с солнцем, helper-ами и тремя лампами.

    Args:
        current: Текущее значение helper-а.

    Returns:
        Адаптер-двойник.
    """
    return _Adapter(
        states={
            "input_number.temperatura_sveta_dnem": "6000",
            "input_number.temperatura_sveta_nochiu": "2000",
        },
        snapshots={
            "sun.sun": {
                "state": "below_horizon",
                "next_setting": "2026-10-22T18:00:00+05:00",
            },
            "input_number.tekushchaia_temperatura": {
                "state": current,
                "min": 2000,
                "max": 6000,
            },
            "light.table": {
                "state": "on",
                "supported_color_modes": ["color_temp"],
                "min_color_temp_kelvin": 2000,
                "max_color_temp_kelvin": 6535,
                "brightness": 180,
                "supported_features": 44,
            },
            "light.off": {
                "state": "off",
                "supported_color_modes": ["color_temp"],
                "min_color_temp_kelvin": 2000,
                "max_color_temp_kelvin": 6535,
            },
            "light.onoff": {
                "state": "on",
                "supported_color_modes": ["onoff"],
            },
        },
    )


def test_deco_light_with_global_flag_is_updated_too() -> None:
    """Декоративный торшер с общей температурой тоже получает обновления.

    Гирлянда без флага остаётся при своём цвете; лампа с обычным освещением и
    торшер с декоративным поведением должны попасть в список службы.
    """
    manifest = Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="gostinaia",
                name="Гостиная",
                devices=[
                    DeviceConfig(
                        id="light.table",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={"use_global_color_temp": True},
                            )
                        ],
                    ),
                    DeviceConfig(
                        id="light.torsher",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="deco_light",
                                priority=10,
                                params={"off_by": "sleep", "use_global_color_temp": True},
                            )
                        ],
                    ),
                    DeviceConfig(
                        id="light.kus",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="deco_light",
                                priority=10,
                                params={"off_by": "sleep"},
                            )
                        ],
                    ),
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )

    assert dict(_lighting_devices(manifest)) == {
        "light.table": 10,
        "light.torsher": 10,
    }


def _service(
    adapter: _Adapter,
    dispatcher: _Dispatcher,
    night_mode_supplier: Any = None,
) -> LightColorTemperatureService:
    """Собрать службу с фиксированным временем 19:30.

    Args:
        adapter: Адаптер-двойник.
        dispatcher: Диспетчер-двойник.
        night_mode_supplier: Признак ночного режима; по умолчанию нет.

    Returns:
        Служба.
    """
    return LightColorTemperatureService(
        adapter=adapter,
        dispatcher=dispatcher,
        manifest=_manifest(),
        now_supplier=lambda _tz: NOW,
        night_mode_supplier=night_mode_supplier,
    )


class TestCurve:
    """Кривая «день → закат → 21:00 → ночь»."""

    def test_day_is_cold(self) -> None:
        """Днём свет холодный."""
        now = datetime(2026, 10, 21, 12, 0, tzinfo=TZ)
        assert (
            target_kelvin(
                now,
                daylight=True,
                sunset=datetime(2026, 10, 21, 18, 0, tzinfo=TZ),
                day_kelvin=6000,
                night_kelvin=2000,
                warm_at=time(21, 0),
            )
            == 6000
        )

    def test_evening_ramps_to_warm(self) -> None:
        """После заката температура линейно идёт к ночной."""
        value = target_kelvin(
            datetime(2026, 10, 21, 19, 30, tzinfo=TZ),
            daylight=False,
            sunset=datetime(2026, 10, 21, 18, 0, tzinfo=TZ),
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )
        assert value == 4000, "к 19:30 свет должен быть ровно посередине"

    def test_warm_at_is_night_value(self) -> None:
        """В 21:00 — максимально тёплый."""
        value = target_kelvin(
            datetime(2026, 10, 21, 21, 0, tzinfo=TZ),
            daylight=False,
            sunset=datetime(2026, 10, 21, 18, 0, tzinfo=TZ),
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )
        assert value == 2000

    def test_warm_at_uses_house_timezone_when_sunset_is_utc(self) -> None:
        """21:00 — по часам дома, даже если закат из HA пришёл в UTC.

        HA отдаёт ``next_setting`` в UTC. Если строить ``warm_at`` в поясе
        заката, кривая заканчивается в 21:00 UTC — в 02:00 по дому. Вчера в
        21:00 helper был 4385 K вместо 2000 K (боевая находка 29.10).
        """
        sunset_utc = datetime(2026, 10, 28, 12, 40, tzinfo=UTC)  # 17:40 дома
        at_20 = target_kelvin(
            datetime(2026, 10, 28, 20, 0, tzinfo=TZ),
            daylight=False,
            sunset=sunset_utc,
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )
        at_21 = target_kelvin(
            datetime(2026, 10, 28, 21, 0, tzinfo=TZ),
            daylight=False,
            sunset=sunset_utc,
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )

        assert at_20 == 3200, "в 20:00 кривая ещё не должна быть у ночи"
        assert at_21 == 2000, "в 21:00 по дому уже самый тёплый свет"

    def test_sunset_from_ha_utc_is_converted_to_house_timezone(self) -> None:
        """Закат HA (UTC) приводится к часам дома до вычитания суток."""
        sunset = LightColorTemperatureService._sunset(
            {"next_setting": "2026-10-29T12:40:00+00:00"},
            False,
            TZ,
        )

        assert sunset == datetime(2026, 10, 28, 17, 40, tzinfo=TZ)

    def test_after_midnight_is_warm(self) -> None:
        """Ночью после 21:00 и до рассвета — тёплый."""
        value = target_kelvin(
            datetime(2026, 10, 22, 1, 0, tzinfo=TZ),
            daylight=False,
            sunset=datetime(2026, 10, 21, 18, 0, tzinfo=TZ),
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )
        assert value == 2000

    def test_missing_sun_uses_time_of_day(self) -> None:
        """Без данных солнца кривая не ломается: днём холодно, ночью тепло."""
        day = target_kelvin(
            datetime(2026, 10, 21, 12, 0, tzinfo=TZ),
            daylight=None,
            sunset=None,
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )
        night = target_kelvin(
            datetime(2026, 10, 22, 1, 0, tzinfo=TZ),
            daylight=None,
            sunset=None,
            day_kelvin=6000,
            night_kelvin=2000,
            warm_at=time(21, 0),
        )
        assert day == 6000
        assert night == 2000


class TestService:
    """Служба пишет helper и обновляет только горящие лампы с color_temp."""

    @pytest.mark.asyncio
    async def test_writes_current_and_updates_on_lights(self) -> None:
        """19:30 — helper 4000 К и команда горящей лампе с сохранением яркости.

        Returns:
            Ничего.
        """
        adapter = _adapter(current="6000")
        dispatcher = _Dispatcher()

        await _service(adapter, dispatcher).check_once()

        writes = [c for c in adapter.calls if c["entity_id"].endswith("tekushchaia_temperatura")]
        assert writes, "текущая температура не записана в helper"
        assert writes[0]["data"]["value"] == 4000

        assert len(dispatcher.intents) == 1, "команда ушла не только горящей лампе"
        intent = dispatcher.intents[0]
        assert intent.device_id == "light.table"
        assert intent.data["color_temp_kelvin"] == 4000
        assert intent.data["brightness"] == 180, "яркость лампы должна сохраниться"
        assert intent.data["transition"] == 300

    @pytest.mark.asyncio
    async def test_same_value_does_not_rewrite_helper(self) -> None:
        """Значение не изменилось — helper не трогаем.

        Returns:
            Ничего.
        """
        adapter = _adapter(current="4000")

        await _service(adapter, _Dispatcher()).check_once()

        assert [
            c for c in adapter.calls if c["entity_id"].endswith("tekushchaia_temperatura")
        ] == []

    @pytest.mark.asyncio
    async def test_lamp_range_clamps_global_value(self) -> None:
        """Лампа уже 3000–5000 К — глобальное значение не выходит за её диапазон.

        Returns:
            Ничего.
        """
        adapter = _adapter()
        lamp = adapter._snapshots["light.table"]
        lamp["min_color_temp_kelvin"] = 3000
        lamp["max_color_temp_kelvin"] = 5000
        dispatcher = _Dispatcher()

        await _service(adapter, dispatcher).check_once()

        assert dispatcher.intents[0].data["color_temp_kelvin"] == 4000


class TestTemperatureAlwaysApplies:
    """Актуальный оттенок дома важнее ручной блокировки.

    Владелец, 2026-10-24: «если лампа уже включена, даже с блокировкой, то
    актуальная температура всё равно должна применяться» и «при включении любой
    лампы она должна использовать температуру, актуальную для этого времени».
    """

    @pytest.mark.asyncio
    async def test_manual_on_gets_temperature_immediately(self) -> None:
        """Лампу включили руками — оттенок поправляется сразу, а не через 5 минут."""
        adapter = _adapter()
        dispatcher = _Dispatcher()

        await _service(adapter, dispatcher).apply_to_device("light.table")

        assert len(dispatcher.intents) == 1, "после ручного включения команда не ушла"
        intent = dispatcher.intents[0]
        assert intent.device_id == "light.table"
        assert intent.data["color_temp_kelvin"] == 4000
        assert intent.data["brightness"] == 180, "яркость человека команда не меняет"
        assert intent.data["transition"] == 5, (
            f"поправка должна быть быстрой, а не пятиминутной: {intent.data}"
        )
        assert intent.bypass_lockout is True, (
            "ручная блокировка не должна оставлять лампу на прошлом оттенке"
        )

    @pytest.mark.asyncio
    async def test_periodic_update_bypasses_manual_lockout(self) -> None:
        """Даже уже горящая лампа получает оттенок при активной блокировке."""
        adapter = _adapter()
        dispatcher = _Dispatcher()

        await _service(adapter, dispatcher).check_once()

        assert dispatcher.intents, "служба не отправила температуру горящей лампе"
        assert dispatcher.intents[0].bypass_lockout is True

    @pytest.mark.asyncio
    async def test_night_light_is_not_made_white(self) -> None:
        """Красный ночник не перекрашивается в общий белый."""
        adapter = _adapter()
        dispatcher = _Dispatcher()
        service = _service(adapter, dispatcher, night_mode_supplier=lambda _device: True)

        await service.apply_to_device("light.table")
        await service.check_once()

        assert dispatcher.intents == [], (
            f"ночной красный свет перекрашен в общий: {dispatcher.intents}"
        )

    @pytest.mark.asyncio
    async def test_device_outside_global_scheme_is_ignored(self) -> None:
        """Лампа без общей температуры не получает команду."""
        adapter = _adapter()
        dispatcher = _Dispatcher()

        await _service(adapter, dispatcher).apply_to_device("light.onoff")

        assert dispatcher.intents == []
