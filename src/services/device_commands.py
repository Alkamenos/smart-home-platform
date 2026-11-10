"""Device command execution for the device service (spec 018, T058).

Extracted from DeviceService: sending a command to Home Assistant and keeping its
status is an integration concern, separate from device storage and access.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from core.models.device import Device
from core.models.device_command import CommandExecutionResponse


logger = logging.getLogger("services.device_service")


class DeviceCommandMixin:
    """Execute commands and track their status."""

    async def execute_command(
        self,
        device_id: UUID,
        command_name: str,
        parameters: dict[str, Any],
        timeout: int = 30,
    ) -> CommandExecutionResponse:
        """T053: Отправляет команду на выполнение в Home Assistant.

        Args:
            device_id: ID устройства
            command_name: Имя команды
            parameters: Параметры команды
            timeout: Таймаут выполнения в секундах (макс 300)

        Returns:
            Объект с информацией о выполненной команде

        Raises:
            ValueError: Если устройство не найдено
            RuntimeError: Если команда не выполнена
        """
        device = await self.get_device(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        if timeout > 300:
            timeout = 300

        try:
            command_id = UUID(int=1)  # Будет заполнено уникальным ID
            from uuid import uuid4

            command_id = uuid4()

            # Устройство для метрик
            device_type = device.device_type or "unknown"
            source_id_str = str(device.source_id)

            # Записываем отправку команды
            self._metrics.record_command_sent(source_id_str, device_type, command_name)

            # Создаем запись о команде
            command_record: dict[str, Any] = {
                "id": command_id,
                "device_id": device_id,
                "command_name": command_name,
                "parameters": parameters,
                "status": "executing",
                "created_at": datetime.utcnow(),
                "completed_at": None,
                "result": None,
                "error": None,
            }

            # Сохраняем запись о команде
            self._commands[command_id] = command_record

            logger.info(
                f"Executing command {command_name} on device {device_id} "
                f"with parameters {parameters}"
            )

            # Отправляем команду в HA через адаптер
            if not self.ha_adapter:
                raise RuntimeError("HA adapter not configured")

            # T055: Асинхронное выполнение команды с таймаутом
            try:
                result = await asyncio.wait_for(
                    self._call_ha_service(device, command_name, parameters),
                    timeout=timeout,
                )

                command_record["status"] = "success"
                command_record["result"] = result
                command_record["completed_at"] = datetime.utcnow()

                # Записываем успех команды
                self._metrics.record_command_success(source_id_str, device_type, command_name)

                logger.info(f"Command {command_name} succeeded on device {device_id}: {result}")

            except TimeoutError as e:
                command_record["status"] = "failed"
                command_record["error"] = f"Command timeout after {timeout} seconds"
                command_record["completed_at"] = datetime.utcnow()

                # Записываем ошибку команды
                self._metrics.record_command_failed(
                    source_id_str, device_type, command_name, "timeout"
                )

                logger.error(f"Command {command_name} timeout on device {device_id}")
                # T059: Публикуем ошибку
                raise RuntimeError(command_record["error"]) from e

            except Exception as e:
                command_record["status"] = "failed"
                command_record["error"] = str(e)
                command_record["completed_at"] = datetime.utcnow()

                # Записываем ошибку команды
                error_type = type(e).__name__
                self._metrics.record_command_failed(
                    source_id_str, device_type, command_name, error_type
                )

                logger.error(f"Command {command_name} failed on device {device_id}: {e}")
                # T059: Публикуем ошибку
                raise RuntimeError(command_record["error"]) from e

            # Возвращаем ответ
            return CommandExecutionResponse(
                id=command_id,
                device_id=device_id,
                command_name=command_name,
                status=command_record["status"],
                created_at=command_record["created_at"],
                completed_at=command_record["completed_at"],
                result=command_record["result"],
                error=command_record["error"],
            )

        except Exception as e:
            logger.error(f"Error executing command: {e}")
            raise

    async def _call_ha_service(
        self,
        device: Device,
        command_name: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Вызывает сервис в Home Assistant.

        Args:
            device: Объект устройства
            command_name: Имя команды
            parameters: Параметры

        Returns:
            Результат выполнения сервиса
        """
        if not self.ha_adapter:
            raise RuntimeError("HA adapter not configured")

        # Формируем domain.service из команды
        domain = device.device_type  # e.g., "light"
        service = command_name  # e.g., "turn_on"

        # Вызываем через адаптер
        result = await self.ha_adapter.call_service(
            domain=domain,
            service=service,
            entity_id=device.ha_entity_id,
            data=parameters,
        )

        # CommandExecutionResponse.result ожидает dict. Раньше здесь стояло `result or {}`,
        # что пропускало непустые не-dict значения (bool от HAAdapter, MagicMock от моков)
        # и приводило к ValidationError при формировании ответа.
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            # HA отвечает списком изменившихся состояний, и он пуст, когда
            # состояние уже было нужным. `bool([])` давал `success: False` при
            # успешно выполненной команде — тот же ложный исход, что и у
            # заглушки маршрута команды (Known Issue #69).
            return {"success": True, "changed_states": result}
        return {"success": bool(result)} if result is not None else {}

    async def get_command_status(
        self,
        device_id: UUID,
        command_id: UUID,
    ) -> dict[str, Any] | None:
        """T055/T056: Получает статус выполненной команды.

        Args:
            device_id: ID устройства
            command_id: ID команды

        Returns:
            Информация о команде или None если не найдена
        """
        command = self._commands.get(command_id)
        if not command or command["device_id"] != device_id:
            return None

        return command

    # ============ T058: События ============
