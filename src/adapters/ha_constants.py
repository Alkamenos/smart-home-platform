"""Общие значения адаптера Home Assistant (BACKLOG B80).

Вынесены из `ha_adapter.py`: их читают и транспорт WebSocket, и сам адаптер, а
когда они лежали в одном модуле с адаптером, вынос транспорта дал бы кольцо
импортов.
"""

from __future__ import annotations

from typing import Final


MANUAL_ON_VALUES = frozenset({"on", "open", "opening", "heat", "auto", "playing"})

MANUAL_OFF_VALUES = frozenset({"off", "closed", "closing", "idle", "paused", "not_home"})

WS_CLOSE_TIMEOUT_SEC = 5.0

SUBSCRIPTION_TIMEOUT_SEC = 10.0

OWN_CONTEXT_KEEP = 256

COMMAND_ECHO_WINDOW_SEC = 20.0

#: Сколько секунд считать «мы только что приказали прибору».
#:
#: Сторож сверки повторяет решение только тогда, когда приказ был **от нас**
#: (BACKLOG B86): расхождение в этом случае значит «команда не дошла», и её надо
#: повторить. Если приказа не было, прибор изменил кто-то другой — человек,
#: кнопка, сценарий — и повторять своё решение значит спорить с человеком
#: (жалоба владельца 2026-10-16: свет в спальне гасили за человеком).
#:
#: Окно вдвое больше цикла сторожа (минута): отказ обнаруживается на следующем
#: проходе, и первый цикл не должен потерять наш же приказ.
DIVERGENCE_COMMAND_WINDOW_SEC: Final[float] = 120.0

GLOBAL_ENTITY_FIELDS: dict[str, str] = {
    "setpoint": "climate_setpoint",
    "comfort_max": "comfort_max",
    "season": "is_winter",
    "feature": "climate_enabled",
    "ac_gate": "ac_allowed",
    "enable": "ventilation_on",
    "airing": "airing_on",
    "exhaust": "exhaust_on",
    "ventilation_feature": "ventilation_enabled",
    "outside_temp": "outside_temperature",
    # Шторы (спека 015).
    "covers_feature": "covers_enabled",
    "my_doma": "my_doma",
    "sobaki_doma": "sobaki_doma",
    "night_close": "covers_close_night",
    "emergency": "cover_emergency",
}

_BOOLEAN_ROLES = frozenset(
    {
        "season",
        "feature",
        "ac_gate",
        "enable",
        "airing",
        "exhaust",
        "ventilation_feature",
        "covers_feature",
        "my_doma",
        "sobaki_doma",
        "night_close",
        "emergency",
    }
)

_NUMERIC_ROLES = frozenset({"setpoint", "comfort_max", "outside_temp"})

_VENTILATION_RETRIGGER_ROLES: frozenset[str] = frozenset(
    {"enable", "ventilation_feature", "season", "airing", "exhaust", "comfort_max", "setpoint"}
)

_COVER_RETRIGGER_ROLES: frozenset[str] = frozenset(
    {"covers_feature", "my_doma", "sobaki_doma", "night_close", "emergency"}
)
