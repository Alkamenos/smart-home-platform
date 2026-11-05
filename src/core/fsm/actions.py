"""Action execution for the FSM engine (spec 018, US4).

Extracted from FSMEngine: resolving an action, enriching its context and sending
the resulting command intents are a separate responsibility from transitions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger


if TYPE_CHECKING:
    from core.commands.dispatcher import CommandDispatcher
    from core.fsm.models import FSMDefinition, State


class ActionMixin:
    """Execute actions and turn their results into context patches."""

    _actions: dict[str, Callable[..., Any]]
    _states: dict[str, State]
    _definitions: dict[str, FSMDefinition]
    _dispatcher: CommandDispatcher | None

    async def _execute_action(
        self,
        action: str | Callable[..., Any] | None,
        entity_id: str,
        context: dict[str, Any],
        log: Any | None = None,
    ) -> dict[str, Any]:
        """Execute an action. Returns a context patch to update the State immutably.

        If the action returns a CommandIntent and a dispatcher is available,
        the intent is submitted to the dispatcher for execution.
        """
        if log is None:
            log = logger

        if action is None:
            return {}

        action_fn = self._actions.get(action) if isinstance(action, str) else action
        if action_fn is None:
            log.error(f"Action '{action}' not found in registry")
            return {}

        state = self._states.get(entity_id)
        try:
            # enrich context with target_device_id and params from FSM definition
            enriched_context = self._enrich_context_for_action(entity_id, context)

            # ПЕРЕДАЕМ ОБА АРГУМЕНТА: state и enriched_context
            result = action_fn(state, enriched_context)
            if asyncio.iscoroutine(result):
                result = await result

            # Если action возвращает CommandIntent и есть dispatcher - отправляем его
            from core.commands.dispatcher import CommandIntent

            # Список шагов — команда с порядком: обогреватель принимает таймер
            # только после включения (живая проверка 2026-10-11), а выключается
            # только после обнуления таймера. Одно намерение такой порядок
            # выразить не может, поэтому шаги отправляются подряд и по порядку.
            intents: list[CommandIntent] | None = None
            if isinstance(result, CommandIntent):
                intents = [result]
            elif isinstance(result, list) and all(isinstance(i, CommandIntent) for i in result):
                intents = list(result)

            if intents is not None:
                if self._dispatcher is None:
                    log.warning(
                        f"No dispatcher available, skipping {len(intents)} CommandIntent(s): {result}"
                    )
                    return {}
                for index, intent in enumerate(intents):
                    log.debug(f"Submitting CommandIntent {index + 1}/{len(intents)}: {intent}")
                    sent = await self._dispatcher.submit(intent)
                    if not sent:
                        if intent.best_effort:
                            # Вспомогательный шаг: без него основное действие
                            # всё равно нужно выполнить. Пример — обнуление
                            # таймера перед выключением обогревателя.
                            log.warning(
                                f"Command step {index + 1}/{len(intents)} not sent "
                                f"({intent.source} → {intent.device_id}); "
                                "continuing: step is best effort"
                            )
                            continue
                        # Дальше идти нельзя: шаг с таймером без включённого
                        # прибора Home Assistant запишет без ошибки, а греть
                        # никто не будет — отказ будет выглядеть как успех.
                        log.warning(
                            f"Command step {index + 1}/{len(intents)} not sent "
                            f"({intent.source} → {intent.device_id}); remaining steps skipped"
                        )
                        return {}
                return {}

            # Если action возвращает dict, считаем это патчем для обновления контекста
            # (для обратной совместимости)
            context_patch = result if isinstance(result, dict) else {}

            name = action_fn.__name__ if hasattr(action_fn, "__name__") else str(action_fn)
            log.debug(f"Action '{name}' executed successfully, context patch: {context_patch}")
            return context_patch
        except Exception as e:
            name = action_fn.__name__ if hasattr(action_fn, "__name__") else str(action_fn)
            log.error(f"Action '{name}' raised exception: {e}")
            return {}

    def _definition_params(self, entity_id: str) -> dict[str, Any]:
        """Параметры поведения автомата.

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Параметры из описания автомата либо пустой словарь.
        """
        definition = self._definitions.get(entity_id)
        if definition is None or not definition.params:
            return {}
        return dict(definition.params)

    def definition_params(self, entity_id: str) -> dict[str, Any]:
        """Публично: параметры поведения автомата (из манифеста).

        Нужны тому, кто решает о поведении снаружи переходов — например, сверке
        вечернего света: она различает свет, гаснущий по отбою
        (``off_by: sleep``), и свет, живущий до рассвета (``off_by: sunrise``).

        Args:
            entity_id: Идентификатор автомата.

        Returns:
            Копия параметров либо пустой словарь.
        """
        return self._definition_params(entity_id)

    def _enrich_context_for_action(self, entity_id: str, context: dict[str, Any]) -> dict[str, Any]:
        """Enrich context with target_device_id and params from FSM definition.

        This ensures action handlers receive the real device ID (e.g., light.kitchen)
        instead of the internal FSM entity_id (e.g., light.kitchen__night_light_20).
        Also adds dispatcher to context so actions can call release().

        Args:
            entity_id: The internal FSM entity_id.
            context: The original context dictionary.

        Returns:
            dict: Enriched context with target_device_id, params, and dispatcher.
        """
        enriched = {**context}

        definition = self._definitions.get(entity_id)
        if definition is not None:
            # Add target_device_id as entity_id for action handlers
            if definition.target_device_id is not None:
                enriched["entity_id"] = definition.target_device_id
                enriched["target_device_id"] = definition.target_device_id
            # Add params from FSM definition
            if definition.params:
                enriched["params"] = definition.params

        # Add dispatcher to context so actions can call release()
        if self._dispatcher is not None:
            enriched["dispatcher"] = self._dispatcher

        return enriched
