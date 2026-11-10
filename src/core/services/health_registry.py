"""Реестр проблем дома: что открыто, что закрыто и когда.

Проблемы приходят из обхода и сторожа в виде плоских словарей. Реестр даёт им
стабильные идентификаторы, сохраняет ``first_seen`` между обходами и
перезапусками, закрывает исчезнувшие и группирует причины одной сущности.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from core.logger import get_logger
from core.models.health import (
    LEVEL_RANK,
    HouseProblem,
    ProblemLevel,
    level_for_kind,
)
from core.persistence.health_store import HealthStore


logger = get_logger(__name__)

#: Сколько дней хранить закрытые проблемы.
DEFAULT_RETENTION_DAYS = 30


class HealthRegistry:
    """Хранить активные и закрытые проблемы, группировать их по сущности.

    Args:
        store: Хранилище состояния.
        clock: Источник времени; подменяется в тестах.
        retention_days: Сколько дней хранить закрытые проблемы.
    """

    def __init__(
        self,
        store: HealthStore,
        clock: Any | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._retention_days = max(1, retention_days)
        self._active: dict[str, HouseProblem] = {}
        self._closed: list[HouseProblem] = []
        self._notification: dict[str, Any] = {}
        self._expectations: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Прочитать состояние из хранилища."""
        state = self._store.load()
        for raw in state.get("problems") or []:
            if not isinstance(raw, dict):
                continue
            self._restore(raw, closed=False)
        for raw in state.get("closed") or []:
            if not isinstance(raw, dict):
                continue
            self._restore(raw, closed=True)
        notification = state.get("notification")
        if isinstance(notification, dict):
            self._notification = dict(notification)
        expectations = state.get("expectations")
        if isinstance(expectations, dict):
            self._expectations = dict(expectations)

    def _restore(self, raw: dict[str, Any], *, closed: bool) -> None:
        """Восстановить одну проблему, не роняя реестр на битой записи.

        Args:
            raw: Словарь из файла.
            closed: Относится ли запись к закрытым.

        Returns:
            Ничего.
        """
        try:
            problem = HouseProblem.from_dict(raw, now=self._now_iso())
        except ValueError as exc:
            logger.warning(f"Здоровье дома: проблема не восстановлена: {exc}")
            return
        if closed:
            self._closed.append(problem)
        else:
            self._active[problem.problem_id] = problem

    def _now_iso(self) -> str:
        """Текущее время ISO-8601 с часовым поясом.

        Returns:
            Строка времени.
        """
        return self._clock().isoformat()

    @property
    def active(self) -> tuple[HouseProblem, ...]:
        """Активные проблемы.

        Returns:
            Кортеж проблем в порядке обнаружения.
        """
        return tuple(self._active.values())

    @property
    def notification(self) -> dict[str, Any]:
        """Состояние уведомления.

        Returns:
            Словарь состояния (может быть пустым).
        """
        return dict(self._notification)

    @property
    def expectations(self) -> dict[str, Any]:
        """Сохранённые ожидания по датчикам.

        Returns:
            Словарь ожиданий.
        """
        return dict(self._expectations)

    def observe_report(
        self,
        problems: list[dict[str, Any]],
        generated_at: str,
        *,
        source: str | None = None,
        close_missing: bool = True,
    ) -> list[dict[str, Any]]:
        """Открыть/подтвердить проблемы и закрыть исчезнувшие.

        Args:
            problems: Плоский список проблем из обхода или сторожа.
            generated_at: Время снимка.
            source: Источник по умолчанию, если в записи его нет.
            close_missing: Закрывать ли активные проблемы, которых нет в снимке.
                ``False`` нужен, когда дом не прочитался: отсутствие данных — не
                повод объявлять датчики здоровыми.

        Returns:
            Сгруппированный список активных проблем для API.
        """
        seen: set[str] = set()
        for raw in problems:
            if not isinstance(raw, dict):
                continue
            data = dict(raw)
            if source and not data.get("source"):
                data["source"] = source
            data.setdefault("first_seen", generated_at)
            data["last_seen"] = generated_at
            if not data.get("level"):
                data["level"] = level_for_kind(str(data.get("kind") or ""))
            problem = HouseProblem.from_dict(data, now=generated_at)
            existing = self._active.get(problem.problem_id)
            if existing is not None:
                problem = HouseProblem(
                    kind=problem.kind,
                    subject=problem.subject,
                    name=problem.name,
                    area=problem.area,
                    level=problem.level,
                    detail=problem.detail,
                    source=problem.source,
                    value=problem.value,
                    first_seen=existing.first_seen,
                    last_seen=generated_at,
                    problem_id=existing.problem_id,
                    reasons=list(problem.reasons),
                )
            elif self._remove_closed(problem.problem_id):
                # Проблема вернулась после снятия: это новое occurrence.
                problem = HouseProblem(
                    kind=problem.kind,
                    subject=problem.subject,
                    name=problem.name,
                    area=problem.area,
                    level=problem.level,
                    detail=problem.detail,
                    source=problem.source,
                    value=problem.value,
                    first_seen=generated_at,
                    last_seen=generated_at,
                    problem_id=problem.problem_id,
                    reasons=list(problem.reasons),
                )
                logger.warning(
                    f"Здоровье дома: проблема вернулась: {problem.kind} "
                    f"{problem.subject or ''} — {problem.detail}"
                )
            else:
                logger.warning(
                    f"Здоровье дома: проблема открыта: {problem.kind} "
                    f"{problem.subject or ''} — {problem.detail}"
                )
            self._active[problem.problem_id] = problem
            seen.add(problem.problem_id)

        if close_missing:
            self._close_missing(seen, generated_at, source=source)
        self._prune_closed()
        self.save()
        return self.grouped()

    def _remove_closed(self, identifier: str) -> bool:
        """Убрать закрытую запись, если проблема вернулась.

        Args:
            identifier: Идентификатор проблемы.

        Returns:
            True, если запись была закрыта и удалена.
        """
        for index, problem in enumerate(self._closed):
            if problem.problem_id == identifier:
                del self._closed[index]
                return True
        return False

    def _close_missing(self, seen: set[str], generated_at: str, source: str | None = None) -> None:
        """Закрыть активные проблемы, которых не было в снимке.

        Если снимок пришёл от одного источника (``source``), закрываются
        только его проблемы: иначе обход дома, не знающий о неприменённых
        командах, закрывал бы их каждый раз.

        Args:
            seen: Идентификаторы, подтверждённые в этом обходе.
            generated_at: Время закрытия.
            source: Источник снимка; ``None`` — сводный снимок по всем.

        Returns:
            Ничего.
        """
        for identifier, problem in list(self._active.items()):
            if identifier in seen:
                continue
            if source is not None and problem.source != source:
                continue
            closed = HouseProblem(
                kind=problem.kind,
                subject=problem.subject,
                name=problem.name,
                area=problem.area,
                level=problem.level,
                detail=problem.detail,
                source=problem.source,
                value=problem.value,
                first_seen=problem.first_seen,
                last_seen=generated_at,
                problem_id=problem.problem_id,
                closed_at=generated_at,
                close_reason="recovered",
                reasons=list(problem.reasons),
            )
            self._closed.append(closed)
            del self._active[identifier]
            logger.info(
                f"Здоровье дома: проблема закрыта: {closed.kind} {closed.subject or ''} — recovered"
            )

    def _prune_closed(self) -> None:
        """Удалить закрытые проблемы старше срока хранения."""
        cutoff = self._clock() - timedelta(days=self._retention_days)
        kept: list[HouseProblem] = []
        for problem in self._closed:
            try:
                closed_at = datetime.fromisoformat(problem.closed_at or problem.last_seen)
            except ValueError:
                closed_at = self._clock()
            if closed_at >= cutoff:
                kept.append(problem)
        self._closed = kept

    def grouped(self) -> list[dict[str, Any]]:
        """Сгруппировать активные проблемы по сущности.

        Returns:
            Список групп: одна строка на сущность, причины внутри.
        """
        groups: dict[str, list[HouseProblem]] = {}
        for problem in self._active.values():
            key = problem.subject or f"__{problem.kind}"
            groups.setdefault(key, []).append(problem)
        result: list[dict[str, Any]] = []
        for problems in groups.values():
            problems.sort(key=lambda item: (LEVEL_RANK.get(item.level, 9), item.first_seen))
            head = problems[0]
            result.append(
                {
                    "id": head.problem_id,
                    "subject": head.subject,
                    "name": head.name,
                    "area": head.area,
                    "level": head.level,
                    "first_seen": head.first_seen,
                    "last_seen": head.last_seen,
                    "reasons": [
                        {
                            "id": item.problem_id,
                            "kind": item.kind,
                            "detail": item.detail,
                            "level": item.level,
                            "first_seen": item.first_seen,
                            "last_seen": item.last_seen,
                        }
                        for item in problems
                    ],
                }
            )
        result.sort(key=lambda item: (LEVEL_RANK.get(item["level"], 9), item["first_seen"]))
        return result

    def snapshot(self) -> dict[str, Any]:
        """Снимок для API: число, уровни и группы.

        Returns:
            Словарь с ``count``, ``levels`` и ``problems``.
        """
        levels = {level.value: 0 for level in ProblemLevel}
        for problem in self._active.values():
            levels[problem.level] = levels.get(problem.level, 0) + 1
        return {
            "count": len(self._active),
            "levels": levels,
            "problems": self.grouped(),
        }

    def fingerprint(self) -> str:
        """Отпечаток состава проблем для антиспама уведомлений.

        Returns:
            Стабильный хэш отсортированных причин.
        """
        items = sorted(
            f"{problem.kind}|{problem.subject or ''}|{problem.detail}"
            for problem in self._active.values()
        )
        return hashlib.sha1(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()

    def set_notification(self, state: dict[str, Any]) -> None:
        """Сохранить состояние уведомления.

        Args:
            state: Словарь состояния.

        Returns:
            Ничего.
        """
        self._notification = dict(state)

    def set_expectations(self, expectations: dict[str, Any]) -> None:
        """Сохранить ожидания по датчикам.

        Args:
            expectations: Сущность → ожидание.

        Returns:
            Ничего.
        """
        self._expectations = dict(expectations)

    def save(self) -> None:
        """Записать состояние в хранилище."""
        self._store.save(
            {
                "problems": [problem.as_dict() for problem in self._active.values()],
                "closed": [problem.as_dict() for problem in self._closed],
                "notification": self._notification,
                "expectations": self._expectations,
            }
        )
