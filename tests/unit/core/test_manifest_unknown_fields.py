"""Неизвестные поля в описании дома (спека 018, US1, D1).

Опечатка в имени поля должна быть ошибкой, а не молчаливым игнором: иначе
`hysteresis` превращается в `histeresis`, и дом работает не так, как записано.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.models.manifest import Manifest


def _minimal() -> dict:
    """Минимальный валидный манифест.

    Returns:
        Словарь с обязательными полями.
    """
    return {
        "instance": {"id": "probe", "name": "Probe", "owner": "probe", "created_at": ""},
        "version": 1,
        "rooms": [],
    }


def test_unknown_top_level_field_is_rejected() -> None:
    """Неизвестное поле верхнего уровня — ошибка с путём."""
    data = {**_minimal(), "histeresis": 0.5}

    with pytest.raises(ValidationError) as error:
        Manifest.model_validate(data)

    assert "histeresis" in str(error.value), (
        "ошибка не назвала поле: утренний разбор не поймёт, что править"
    )


def test_unknown_room_field_is_rejected() -> None:
    """Неизвестное поле комнаты — тоже ошибка."""
    data = _minimal()
    data["rooms"] = [{"id": "spalnia", "name": "Спальня", "unknown": 1}]

    with pytest.raises(ValidationError) as error:
        Manifest.model_validate(data)

    assert "unknown" in str(error.value)


def test_unknown_device_field_is_rejected() -> None:
    """Неизвестное поле прибора не прощается."""
    data = _minimal()
    data["rooms"] = [
        {
            "id": "spalnia",
            "name": "Спальня",
            "devices": [{"id": "switch.x", "type": "climate", "foo": 1}],
        }
    ]

    with pytest.raises(ValidationError) as error:
        Manifest.model_validate(data)

    assert "foo" in str(error.value)


def test_extensions_namespace_is_allowed() -> None:
    """Явное пространство расширений допускается и сохраняется."""
    data = {**_minimal(), "extensions": {"vendor": {"note": "test"}}}

    manifest = Manifest.model_validate(data)

    assert manifest.extensions == {"vendor": {"note": "test"}}
