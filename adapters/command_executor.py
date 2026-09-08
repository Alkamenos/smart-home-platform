"""
Command Executor - Выполнение команд устройствами через EventBus

Принципы:
- Dependency Inversion: core не знает об adapters
- Event-driven: команды выполняются через подписку на события
- Single Responsibility: только выполнение команд, без логики FSM
"""

from __future__ import annotations
from typing import Any
from adapters.base import BaseAdapter


class CommandExecutor:
    """
    Обработчик команд для устройств
    
    Подписывается на событие "device.command" и вызывает adapter.send_command
    
    Usage:
        executor = CommandExecutor(adapter, event_bus, logger)
        # Далее автоматически обрабатывает все события device.command
    """
    
    def __init__(self, adapter: BaseAdapter, event_bus, logger):
        """
        Инициализация CommandExecutor
        
        Args:
            adapter: Адаптер для отправки команд устройствам
            event_bus: Шина событий для подписки на device.command
            logger: Логгер для вывода сообщений
        """
        self._adapter = adapter
        self._event_bus = event_bus
        self._logger = logger
        
        # Подписываемся на события команд
        event_bus.subscribe("device.command", self._handle_command)
        
        self._logger.info("CommandExecutor initialized")
    
    def _handle_command(self, data: dict[str, Any]) -> None:
        """
        Обработчик события device.command
        
        Args:
            data: Данные команды:
                - entity_id: ID устройства
                - command: Команда (turn_on, turn_off, set_hvac_mode и т.д.)
                - attributes: Дополнительные атрибуты (brightness, temperature и т.д.)
                - source: Источник команды (fsm, manual и т.д.)
                - reason: Причина выполнения команды
                - timestamp: Время выполнения
        """
        entity_id = data.get("entity_id")
        command = data.get("command")
        attributes = data.get("attributes", {})
        source = data.get("source", "unknown")
        reason = data.get("reason", "")
        timestamp = data.get("timestamp")
        
        if not entity_id or not command:
            self._logger.warning(
                f"Invalid command: missing entity_id or command",
                data=data
            )
            return
        
        try:
            self._logger.debug(
                f"Executing command {command} for {entity_id}",
                entity_id=entity_id,
                command=command,
                attributes=attributes,
                source=source,
                reason=reason
            )
            
            # Вызываем адаптер для выполнения команды
            self._adapter.send_command(entity_id, command, attributes)
            
            self._logger.info(
                f"Command executed: {command} for {entity_id}",
                entity_id=entity_id,
                command=command,
                source=source,
                reason=reason,
                timestamp=timestamp
            )
            
        except Exception as e:
            self._logger.error(
                f"Command execution failed: {e}",
                entity_id=entity_id,
                command=command,
                error=str(e),
                source=source
            )
    
    def shutdown(self) -> None:
        """Отписаться от событий при остановке"""
        self._event_bus.unsubscribe("device.command", self._handle_command)
        self._logger.info("CommandExecutor shutdown complete")
