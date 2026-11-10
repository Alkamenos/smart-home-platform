"""Модели здоровья дома: проблема, её уровень и состояние.

Проблемы приходят из двух источников — обхода датчиков и сторожа автоматов —
и должны иметь одну форму, чтобы интерфейс, API и уведомление не расходились.
Здесь только данные и правила валидации; поиск проблем и хранение живут в
`core.services.health_registry` и `core.persistence.health_store`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProblemLevel(StrEnum):
    """Важность проблемы для человека."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ProblemKind(StrEnum):
    """Вид проблемы. Строковые значения попадают в API и журнал."""

    STALE = "stale"
    LOW_BATTERY = "low_battery"
    BATTERY_SILENT = "battery_silent"
    UNAVAILABLE = "unavailable"
    MISSING_ENTITY = "missing_entity"
    HOUSE_UNREADABLE = "house_unreadable"
    COMMAND_NOT_APPLIED = "command_not_applied"
    DEVICE_MISMATCH = "device_mismatch"
    FSM_STUCK = "fsm_stuck"
    HA_DISCONNECTED = "ha_disconnected"


#: Виды, которые нельзя прятать в «информацию»: дом не читается, связи нет,
#: датчик безопасности молчит.
CRITICAL_KINDS = frozenset(
    {
        ProblemKind.HOUSE_UNREADABLE.value,
        ProblemKind.HA_DISCONNECTED.value,
    }
)

#: Виды, которые достаточно показать как предупреждение.
WARNING_KINDS = frozenset(
    {
        ProblemKind.STALE.value,
        ProblemKind.LOW_BATTERY.value,
        ProblemKind.BATTERY_SILENT.value,
        ProblemKind.UNAVAILABLE.value,
        ProblemKind.COMMAND_NOT_APPLIED.value,
        ProblemKind.DEVICE_MISMATCH.value,
        ProblemKind.FSM_STUCK.value,
    }
)

#: Порядок уровней для сортировки: критичное выше предупреждения.
LEVEL_RANK = {
    ProblemLevel.CRITICAL.value: 0,
    ProblemLevel.WARNING.value: 1,
    ProblemLevel.INFO.value: 2,
}


def level_for_kind(kind: str) -> str:
    """Уровень проблемы по её виду.

    Args:
        kind: Вид проблемы.

    Returns:
        ``critical``, ``warning`` или ``info``.
    """
    value = str(kind).strip().lower()
    if value in CRITICAL_KINDS:
        return ProblemLevel.CRITICAL.value
    if value in WARNING_KINDS:
        return ProblemLevel.WARNING.value
    return ProblemLevel.INFO.value


def problem_id(kind: str, subject: str | None) -> str:
    """Стабильный идентификатор проблемы.

    Один вид по одной сущности — одна запись между обходами и перезапусками.
    Идентификатор не зависит от времени и текста причины.

    Args:
        kind: Вид проблемы.
        subject: Сущность или прибор; ``None`` для проблем дома.

    Returns:
        Короткий устойчивый хэш.
    """
    raw = f"{str(kind).strip().lower()}|{str(subject or '').strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SensorExpectation:
    """Ожидание по датчику: как часто он обычно присылает показания.

    Attributes:
        entity_id: Сущность.
        expected_interval_sec: Типичный интервал между показаниями, сек.
        stale_after_sec: С какого возраста показание считается молчащим.
        source: Откуда взят интервал: ``history``, ``class`` или ``manifest``.
        samples: Сколько интервалов легло в расчёт.
    """

    entity_id: str
    expected_interval_sec: float
    stale_after_sec: float
    source: str
    samples: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Превратить ожидание в словарь для состояния и API.

        Returns:
            Словарь с полями ожидания.
        """
        return {
            "entity_id": self.entity_id,
            "expected_interval_sec": self.expected_interval_sec,
            "stale_after_sec": self.stale_after_sec,
            "source": self.source,
            "samples": self.samples,
        }


@dataclass(frozen=True)
class HouseProblem:
    """Одна причина по одной сущности.

    Attributes:
        kind: Вид проблемы из :class:`ProblemKind`.
        subject: Сущность или прибор; пусто для проблем дома.
        name: Человеческое имя.
        area: Комната или локация; пусто, если неизвестно.
        level: Уровень важности.
        detail: Причина человеческим языком.
        source: Источник: ``health``, ``watchdog`` или ``command``.
        value: Показание на момент обнаружения.
        first_seen: ISO-8601 первого обнаружения.
        last_seen: ISO-8601 последнего подтверждения.
        problem_id: Стабильный идентификатор; вычисляется, если не задан.
        closed_at: ISO-8601 снятия; ``None`` у активной.
        close_reason: Причина снятия.
    """

    kind: str
    subject: str | None
    name: str
    area: str
    level: str
    detail: str
    source: str
    value: str | None
    first_seen: str
    last_seen: str
    problem_id: str = ""
    closed_at: str | None = None
    close_reason: str | None = None
    reasons: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Проверить обязательные поля и вычислить идентификатор.

        Raises:
            ValueError: Если время противоречиво или уровень неизвестен.
        """
        if not self.problem_id:
            object.__setattr__(self, "problem_id", problem_id(self.kind, self.subject))
        if self.level not in LEVEL_RANK:
            raise ValueError(f"неизвестный уровень проблемы: {self.level!r}")
        if self.closed_at is not None and self.closed_at < self.first_seen:
            raise ValueError("closed_at раньше first_seen")
        if self.last_seen < self.first_seen:
            raise ValueError("last_seen раньше first_seen")

    @property
    def is_open(self) -> bool:
        """Активна ли проблема.

        Returns:
            True, если ещё не снята.
        """
        return self.closed_at is None

    def as_dict(self) -> dict[str, Any]:
        """Превратить проблему в словарь для API и журнала.

        Returns:
            Словарь с полями из спецификации.
        """
        return {
            "id": self.problem_id,
            "kind": self.kind,
            "subject": self.subject,
            "name": self.name,
            "area": self.area,
            "level": self.level,
            "detail": self.detail,
            "source": self.source,
            "value": self.value,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, now: str) -> HouseProblem:
        """Собрать проблему из записи обхода или сторожа.

        Проблемы старого формата не имеют ``first_seen``/``level`` — их
        дополняем значениями по умолчанию, а не отвергаем: иначе первый запуск
        после обновления потерял бы все текущие проблемы.

        Args:
            data: Словарь проблемы (``kind``, ``subject``, ``detail``, ...).
            now: Время текущего обхода для отсутствующих полей.

        Returns:
            Проблема.
        """
        kind = str(data.get("kind") or "unknown")
        subject = data.get("subject")
        first_seen = str(data.get("first_seen") or now)
        last_seen = str(data.get("last_seen") or first_seen)
        return cls(
            kind=kind,
            subject=str(subject) if subject is not None else None,
            name=str(data.get("name") or data.get("subject") or "проблема"),
            area=str(data.get("area") or ""),
            level=str(data.get("level") or level_for_kind(kind)),
            detail=str(data.get("detail") or ""),
            source=str(data.get("source") or "health"),
            value=None if data.get("value") is None else str(data.get("value")),
            first_seen=first_seen,
            last_seen=last_seen,
            problem_id=str(data.get("id") or problem_id(kind, subject)),
            closed_at=str(data["closed_at"]) if data.get("closed_at") else None,
            close_reason=str(data["close_reason"]) if data.get("close_reason") else None,
            reasons=list(data.get("reasons") or []),
        )
