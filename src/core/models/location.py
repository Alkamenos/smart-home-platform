"""Снимок состояния локации: показания датчиков и производные (спека 016).

Локация — именованная область наблюдения: комната манифеста, улица или грядки.
Снимок отвечает на вопрос «что сейчас известно об этой локации»: по каждой роли
датчиков — значение, единица измерения и время последнего показания, признак
молчания и доступности, а также производные (человек в локации, время с
последнего движения, открытые окна и двери, число молчащих датчиков).

Производные **вычисляются при чтении** из сохранённых показаний (research.md
D6): отдельного планировщика нет, и производная всегда согласована с тем, что
реально запомнено. Молчание при этом становится видимым (FR-011): «значение не
изменилось» и «датчик пропал» — разные вещи.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


#: Значения, которые означают «датчик недоступен». Пустая строка — тоже: HA
#: отдаёт её, когда у сущности нет состояния.
UNAVAILABLE_VALUES = frozenset({"unavailable", "unknown", ""})

#: Значения, которые считаются «включено» у булевых ролей (движение, контакт,
#: дождь). Home Assistant пишет ``on``/``off``, но бинарные датчики бывают и
#: ``detected``/``clear``, а контакт — ``open``/``closed``.
ON_VALUES = frozenset({"on", "true", "1", "open", "opened", "detected"})


class SensorReading(BaseModel):
    """Последнее показание датчика, как его запомнила платформа.

    Attributes:
        entity_id: Сущность Home Assistant.
        role: Роль датчика в локации (``temperature``, ``motion``, …).
        value: Значение состояния (число или строка).
        unit: Единица измерения из Home Assistant либо ``None``.
        at: Время, когда платформа увидела это значение.
        available: Было ли состояние доступно (не ``unavailable``/``unknown``).
        last_on_at: Когда датчик в последний раз был «включён». Нужно движению:
            «сейчас off» — обычное состояние датчика движения, а «человек ушёл
            пять минут назад» считается по последнему ``on``.
    """

    entity_id: str
    role: str
    value: Any
    unit: str | None = None
    at: datetime
    available: bool = True
    last_on_at: datetime | None = None

    def is_on(self) -> bool:
        """Было ли последнее значение «включено».

        Returns:
            True, если значение входит в набор «включённых».
        """
        return str(self.value).strip().lower() in ON_VALUES


class Reading(BaseModel):
    """Показание датчика в снимке локации.

    Attributes:
        value: Значение состояния.
        unit: Единица измерения либо ``None``.
        at: Время последнего показания в формате ISO.
        stale: Датчик молчит дольше порога локации (FR-011).
        available: Состояние доступно (не ``unavailable``/``unknown``).
        entity_id: Сущность, откуда пришло показание.
    """

    value: Any
    unit: str | None = None
    at: str
    stale: bool = False
    available: bool = True
    entity_id: str


class LocationRef(BaseModel):
    """Ссылка на локацию внутри снимка.

    Attributes:
        id: Идентификатор локации.
        name: Человекочитаемое имя.
        kind: Вид зоны (``room``, ``outdoor``, ``garden``, ``other``).
    """

    id: str
    name: str
    kind: str


class LocationSnapshot(BaseModel):
    """Снимок локации: показания по ролям и производные.

    Attributes:
        location: Кто это — идентификатор, имя и вид.
        at: Время снимка в формате ISO.
        available: Есть ли в локации хотя бы одно доступное показание.
        readings: Роль датчика → список показаний (у роли бывает несколько
            датчиков: две температуры — два показания).
        derived: Производные величины (присутствие, последнее движение,
            открытые проёмы, молчащие датчики).
    """

    location: LocationRef
    at: str
    available: bool
    readings: dict[str, list[Reading]] = Field(default_factory=dict)
    derived: dict[str, Any] = Field(default_factory=dict)


def build_snapshot(
    *,
    location_id: str,
    name: str,
    kind: str,
    readings: list[SensorReading],
    now: datetime,
    stale_after_sec: int,
    presence_window_sec: int,
) -> LocationSnapshot:
    """Собрать снимок локации из сохранённых показаний.

    Args:
        location_id: Идентификатор локации.
        name: Человекочитаемое имя.
        kind: Вид зоны.
        readings: Последние показания датчиков локации.
        now: Момент чтения снимка (по нему считаются молчание и присутствие).
        stale_after_sec: Порог молчания датчика, секунды.
        presence_window_sec: Окно присутствия после движения, секунды.

    Returns:
        Снимок локации с производными.
    """
    grouped: dict[str, list[Reading]] = {}
    stale_sensors: list[str] = []
    available_count = 0

    for reading in readings:
        age_sec = (now - reading.at).total_seconds()
        stale = age_sec > stale_after_sec
        available = reading.available and not _is_unavailable(reading.value)
        grouped.setdefault(reading.role, []).append(
            Reading(
                value=reading.value,
                unit=reading.unit,
                at=reading.at.isoformat(),
                stale=stale,
                available=available,
                entity_id=reading.entity_id,
            )
        )
        if stale:
            stale_sensors.append(reading.entity_id)
        if available:
            available_count += 1

    # Только доступные датчики участвуют в производных: «человек в комнате»,
    # посчитанный по мёртвому датчику движения, — это ложь (edge case спеки).
    live = [r for r in readings if r.available and not _is_unavailable(r.value)]
    motion_ons = [r.last_on_at for r in live if r.role == "motion" and r.last_on_at is not None]
    last_motion_at = max(motion_ons) if motion_ons else None
    occupied = (
        last_motion_at is not None and (now - last_motion_at).total_seconds() <= presence_window_sec
    )
    contacts_open = sorted(r.entity_id for r in live if r.role == "contact" and r.is_on())

    derived: dict[str, Any] = {
        "occupied": occupied,
        "last_motion_at": last_motion_at.isoformat() if last_motion_at else None,
        "last_motion_ago_sec": (
            int((now - last_motion_at).total_seconds()) if last_motion_at else None
        ),
        "contacts_open": contacts_open,
        "stale_count": len(stale_sensors),
        "stale_sensors": sorted(stale_sensors),
        "available_count": available_count,
        "sensor_count": len(readings),
    }

    return LocationSnapshot(
        location=LocationRef(id=location_id, name=name, kind=kind),
        at=now.isoformat(),
        available=available_count > 0,
        readings=grouped,
        derived=derived,
    )


def _is_unavailable(value: Any) -> bool:
    """Недоступно ли значение состояния.

    Args:
        value: Значение состояния из Home Assistant.

    Returns:
        True для ``unavailable``, ``unknown`` и пустой строки.
    """
    return str(value).strip().lower() in UNAVAILABLE_VALUES
