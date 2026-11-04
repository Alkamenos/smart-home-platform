"""Decision journal for the FSM engine (spec 018, US4).

Extracted from FSMEngine: recording why a transition happened (or did not) is a
separate responsibility from deciding the transition itself.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from core.events.fsm_events import REASON_TEXT
from core.fsm.models import Decision


class DecisionMixin:
    """Record the last decision for every automaton."""

    _decisions: dict[str, Decision]

    def _get_reason_text(self, reason_code: str) -> str:
        """Get human-readable text for a reason code.

        Falls back to the reason_code itself if not found in REASON_TEXT dictionary.

        Args:
            reason_code: The machine-readable reason code.

        Returns:
            Human-readable reason text.
        """
        return REASON_TEXT.get(reason_code, reason_code)

    def _record_decision(
        self,
        entity_id: str,
        outcome: str,
        reason_code: str | None,
        reason_text: str | None,
        trigger: str | None,
    ) -> None:
        """Record a decision (transition or rejection).

        Args:
            entity_id: The entity making the decision.
            outcome: 'on', 'off', 'none', or 'denied'.
            reason_code: Machine-readable reason code (from GUARD_DENIAL_REASONS or action name).
            reason_text: Human-readable reason (if None, determined from reason_code).
            trigger: The event that triggered this decision.
        """
        if reason_text is None and reason_code is not None:
            reason_text = self._get_reason_text(reason_code)
        if reason_text is None:
            reason_text = "неизвестно"

        decision = Decision(
            at=time.time(),
            outcome=outcome,
            reason_code=reason_code,
            reason_text=reason_text,
            trigger=trigger,
        )
        self._decisions[entity_id] = decision

    def _record_transition_decision(
        self, entity_id: str, event: str, action: str | Callable[..., Any] | None
    ) -> None:
        """Записать решение о переходе (T005, FR-005).

        Вид решения (включение/выключение) выводится из имени действия: так
        журнал решений остаётся человекочитаемым без разбора интентов.

        Args:
            entity_id: Идентификатор автомата.
            event: Событие, вызвавшее переход.
            action: Действие перехода (имя или функция).

        Returns:
            Ничего.
        """
        # Record the decision (T005, FR-005)
        action_name = action if isinstance(action, str) else None
        outcome = "none"
        reason_code = None
        if action_name:
            # Determine on/off from action name (T007)
            if "_off" in action_name.lower():
                outcome = "off"
                reason_code = "action_off"
            elif "_on" in action_name.lower() or action_name.lower().startswith("turn_on"):
                outcome = "on"
                reason_code = "action_on"
            else:
                outcome = "on"  # Assume on for unknown actions
                reason_code = "action"
        self._record_decision(
            entity_id=entity_id,
            outcome=outcome,
            reason_code=reason_code,
            reason_text=None,  # Will be determined
            trigger=event,
        )
