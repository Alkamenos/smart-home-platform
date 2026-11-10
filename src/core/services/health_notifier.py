"""Persistent-уведомление Home Assistant о проблемах дома.

Одно уведомление на дом: обновляется, когда меняется состав проблем, и не
повторяется чаще раза в сутки при неизменном составе. Когда проблем нет,
уведомление снимается. Состояние переживает перезапуск, поэтому после рестарта
не приходит то же самое сообщение заново.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from core.logger import get_logger
from core.services.problems import summary_text


logger = get_logger(__name__)

#: Идентификатор уведомления в Home Assistant: одно на дом.
NOTIFICATION_ID = "behavioral_platform_house_problems"

#: Не чаще одного обновления при неизменном составе, часов.
DEFAULT_REPEAT_HOURS = 24.0


class HealthNotifier:
    """Публиковать сводку проблем в persistent-уведомление Home Assistant.

    Args:
        create: Асинхронная функция ``(title, message, notification_id) -> bool``.
        dismiss: Асинхронная функция ``(notification_id) -> bool``.
        registry: Реестр проблем; хранит состояние уведомления.
        repeat_hours: Минимальный интервал повторного уведомления при том же
            составе.
        clock: Источник времени; подменяется в тестах.
        notification_id: Идентификатор уведомления.
    """

    def __init__(
        self,
        create: Callable[[str, str, str], Any],
        dismiss: Callable[[str], Any],
        registry: Any | None = None,
        repeat_hours: float = DEFAULT_REPEAT_HOURS,
        clock: Callable[[], datetime] | None = None,
        notification_id: str = NOTIFICATION_ID,
    ) -> None:
        self._create = create
        self._dismiss = dismiss
        self._registry = registry
        self._repeat = timedelta(hours=max(0.0, float(repeat_hours)))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._notification_id = notification_id
        self._state: dict[str, Any] = {}
        if registry is not None:
            self._state = dict(registry.notification)

    async def publish(self, report: dict[str, Any]) -> dict[str, Any]:
        """Обновить уведомление по снимку проблем.

        Args:
            report: Снимок с ``problems``.

        Returns:
            Состояние уведомления после решения.
        """
        problems = list(report.get("problems") or [])
        count = len(problems)
        fingerprint = self._fingerprint(problems)
        now = self._now()
        state = dict(self._state)

        if count == 0:
            if state.get("active"):
                if await self._dismiss_quietly():
                    state = {
                        "fingerprint": "",
                        "last_sent_at": now.isoformat(),
                        "last_count": 0,
                        "active": False,
                        "dirty": False,
                    }
                else:
                    state["dirty"] = True
            else:
                state.setdefault("fingerprint", "")
                state.setdefault("active", False)
                state["dirty"] = False
            self._save(state)
            return state

        changed = fingerprint != state.get("fingerprint") or not state.get("active")
        if not changed and not self._due(state.get("last_sent_at"), now):
            return state

        title = f"Проблемы дома: {count}"
        message = summary_text(problems)
        if await self._create_quietly(title, message):
            state = {
                "fingerprint": fingerprint,
                "last_sent_at": now.isoformat(),
                "last_count": count,
                "active": True,
                "dirty": False,
            }
            logger.info(
                f"Уведомление HA: создано/обновлено, проблем {count} ({self._notification_id})"
            )
        else:
            state["dirty"] = True
            logger.warning("Уведомление HA не отправлено: Home Assistant не подтвердил вызов")
        self._save(state)
        return state

    def _fingerprint(self, problems: list[dict[str, Any]]) -> str:
        """Стабильный отпечаток состава проблем.

        Args:
            problems: Плоский список проблем.

        Returns:
            Хэш состава.
        """
        items = sorted(
            f"{item.get('kind')}|{item.get('subject')}|{item.get('detail')}" for item in problems
        )
        return hashlib.sha1(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _now(self) -> datetime:
        """Текущее время с часовым поясом.

        Returns:
            Момент времени.
        """
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _due(self, last_sent_at: Any, now: datetime) -> bool:
        """Пора ли повторить уведомление при том же составе.

        Args:
            last_sent_at: Время последнего уведомления (ISO).
            now: Текущее время.

        Returns:
            True, если срок повтора наступил.
        """
        if not isinstance(last_sent_at, str) or not last_sent_at:
            return True
        try:
            moment = datetime.fromisoformat(last_sent_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return now - moment >= self._repeat

    async def _create_quietly(self, title: str, message: str) -> bool:
        """Позвать создание уведомления, не роняя сводку.

        Args:
            title: Заголовок.
            message: Текст.

        Returns:
            True, если Home Assistant подтвердил вызов.
        """
        try:
            result = self._create(title, message, self._notification_id)
            if hasattr(result, "__await__"):
                result = await result
            return result is not False
        except Exception as exc:  # noqa: BLE001 — доставка не отменяет обход
            logger.warning(f"Уведомление HA: создание не удалось: {exc}")
            return False

    async def _dismiss_quietly(self) -> bool:
        """Позвать снятие уведомления, не роняя сводку.

        Returns:
            True, если Home Assistant подтвердил вызов.
        """
        try:
            result = self._dismiss(self._notification_id)
            if hasattr(result, "__await__"):
                result = await result
            return result is not False
        except Exception as exc:  # noqa: BLE001 — доставка не отменяет обход
            logger.warning(f"Уведомление HA: снятие не удалось: {exc}")
            return False

    def _save(self, state: dict[str, Any]) -> None:
        """Сохранить состояние уведомления в реестре.

        Args:
            state: Состояние.

        Returns:
            Ничего.
        """
        self._state = dict(state)
        if self._registry is not None:
            self._registry.set_notification(state)
            self._registry.save()

    def describe(self) -> dict[str, Any]:
        """Описание состояния для журнала и готовности.

        Returns:
            Словарь состояния.
        """
        return {
            "notification_id": self._notification_id,
            "active": bool(self._state.get("active")),
            "last_sent_at": self._state.get("last_sent_at"),
            "dirty": bool(self._state.get("dirty")),
        }
