"""Тревоги из обхода дома: то, чего не видит панель приборов манифеста (F6).

Обход дома смотрит **весь** дом, а панель «Дом» — только приборы манифеста. Первая
же польза видна на живых данных: датчики улицы и грядок недоступны, а батарейка
уличного датчика террасы села до 1 % — и то, и другое должно попадать в «Требует
внимания».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from webui.services.alerts import KIND_HEALTH, alerts_from_health


def _report(*problems: dict[str, object]) -> dict[str, object]:
    """Снимок обхода с проблемами.

    Args:
        *problems: Записи проблем.

    Returns:
        Снимок обхода.
    """
    return {"generated_at": "2026-10-15T12:00:00+00:00", "problems": list(problems), "areas": {}}


def test_unavailable_sensor_becomes_warning() -> None:
    """Недоступный датчик — «вмешаться»."""
    alerts = alerts_from_health(
        _report(
            {
                "kind": "unavailable",
                "subject": "sensor.ulitsa_temperature",
                "detail": "Датчик улицы (локация:Улица): датчик не отвечает",
                "at": None,
            }
        )
    )

    assert len(alerts) == 1
    assert alerts[0].kind == KIND_HEALTH
    assert alerts[0].severity == "warning"
    assert "не отвечает" in alerts[0].detail


def test_low_battery_becomes_warning() -> None:
    """Батарейка на исходе — «вмешаться»."""
    alerts = alerts_from_health(
        _report(
            {
                "kind": "low_battery",
                "subject": "sensor.datchik_temperatury_terassa_battery",
                "detail": "Заряд 1 %",
                "at": None,
            }
        )
    )

    assert alerts[0].severity == "warning"


def test_stale_sensor_is_only_information() -> None:
    """Молчание датчика — «знать», а не «вмешаться»: это не поломка."""
    alerts = alerts_from_health(
        _report(
            {
                "kind": "stale",
                "subject": "sensor.sad_temperature",
                "detail": "молчит 7 ч",
                "at": None,
            }
        )
    )

    assert alerts[0].severity == "info"


def test_empty_report_gives_no_alerts() -> None:
    """Обхода не было — тревог нет, и это не ошибка."""
    assert alerts_from_health(None) == []
    assert alerts_from_health({"problems": []}) == []


def test_unreadable_house_is_a_warning_not_a_note() -> None:
    """Непрочитанный дом — «вмешаться», а не «знать» (аудит 2026-10-16, К-3).

    Молчание обхода не должно выглядеть как порядок в доме: панель тревог
    обязана сказать, что обход не состоялся.

    Returns:
        Ничего.
    """
    alerts = alerts_from_health(
        _report(
            {
                "kind": "house_unreadable",
                "subject": None,
                "detail": "состояния Home Assistant не прочитаны",
                "at": None,
            }
        )
    )

    assert len(alerts) == 1, f"непрочитанный дом не породил тревоги: {alerts}"
    assert alerts[0].kind == KIND_HEALTH
    assert alerts[0].severity == "warning", "молчание обхода выдано за порядок в доме"
