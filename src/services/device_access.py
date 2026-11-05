"""Device access control for the device service (spec 018, T058).

Extracted from DeviceService: checking, granting and revoking per-user access is
a policy concern, separate from device storage and Home Assistant synchronization.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from core.models.device import Device
from core.models.device_access import DeviceAccess


logger = logging.getLogger("services.device_service")


class DeviceAccessMixin:
    """Check and change per-user device access."""

    async def check_device_access(
        self,
        device_id: UUID,
        user_id: str,
        required_role: Literal["viewer", "controller", "admin"] = "viewer",
    ) -> bool:
        """Проверяет имеет ли пользователь доступ к устройству с требуемой ролью.

        Args:
            device_id: Идентификатор устройства
            user_id: Идентификатор пользователя
            required_role: Требуемая роль (viewer, controller, admin)

        Returns:
            True если пользователь имеет доступ, False иначе
        """
        try:
            # Получаем запись доступа из persistence
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.warning("Persistence модуль не имеет device_access")
                return False

            access = await self.persistence.device_access.load_access_for_user_device(
                device_id, user_id
            )

            if not access:
                logger.debug(f"Доступ не найден для user {user_id} -> device {device_id}")
                return False

            # Проверяем что роль достаточно для требуемого действия
            role_hierarchy = {"viewer": 0, "controller": 1, "admin": 2}
            user_level = role_hierarchy.get(access.role, -1)
            required_level = role_hierarchy.get(required_role, -1)

            if user_level >= required_level:
                logger.debug(
                    f"Доступ разрешен: user {user_id} имеет роль {access.role} для device {device_id}"
                )
                return True

            logger.debug(
                f"Доступ запрещен: user {user_id} имеет роль {access.role}, требуется {required_role}"
            )
            return False

        except Exception as e:
            logger.error(f"Ошибка проверки доступа: {e}")
            return False

    async def grant_access(
        self,
        device_id: UUID,
        user_id: str,
        role: Literal["viewer", "controller", "admin"],
        granted_by: str,
    ) -> DeviceAccess | None:
        """Предоставляет пользователю доступ к устройству.

        Args:
            device_id: Идентификатор устройства
            user_id: Идентификатор пользователя
            role: Роль пользователя (viewer, controller, admin)
            granted_by: ID пользователя (администратора) который предоставляет доступ

        Returns:
            Созданная запись доступа или None если ошибка
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.error("Persistence модуль не имеет device_access")
                return None

            # Проверяем что пользователь грантер является админом
            # (эту проверку должен делать route handler)

            # Устройство может не существовать ещё (grant до синка) —
            # доступ выдаётся на идентификатор устройства (device-blind)

            # Проверяем что роль валидна
            if role not in ["viewer", "controller", "admin"]:
                logger.warning(f"Невалидная роль: {role}")
                return None

            # Проверяем существует ли уже доступ (для определения действия)
            previous_access = await self.persistence.device_access.load_access_for_user_device(
                device_id, user_id
            )
            previous_role: Literal["viewer", "controller", "admin"] | None = (
                previous_access.role if previous_access else None
            )

            # Удаляем существующий доступ если есть
            if previous_access:
                await self.persistence.device_access.delete_access(previous_access.id)

            # Создаем новую запись доступа
            access = DeviceAccess(
                device_id=device_id, user_id=user_id, role=role, granted_by=granted_by
            )

            # Сохраняем в persistence
            await self.persistence.device_access.save_access(access)

            # T070: Публикуем событие изменения доступа
            action: Literal["granted", "updated"] = "updated" if previous_role else "granted"
            await self._publish_access_changed_event(
                device_id=device_id,
                user_id=user_id,
                action=action,
                role=role,
                previous_role=previous_role,
                granted_by=granted_by,
            )

            logger.info(
                f"Доступ предоставлен: user {user_id} роль {role} для device {device_id} (грантер: {granted_by})"
            )

            return access

        except Exception as e:
            logger.error(f"Ошибка предоставления доступа: {e}")
            return None

    async def revoke_access(self, access_id: UUID) -> bool:
        """Отзывает доступ пользователя к устройству.

        Args:
            access_id: Идентификатор записи доступа для удаления

        Returns:
            True если удалено успешно
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.error("Persistence модуль не имеет device_access")
                return False

            # Получаем запись доступа перед удалением (для события)
            access = await self.persistence.device_access.load_access(access_id)

            result: bool = await self.persistence.device_access.delete_access(access_id)

            if result and access:
                # T070: Публикуем событие отзыва доступа
                await self._publish_access_changed_event(
                    device_id=access.device_id,
                    user_id=access.user_id,
                    action="revoked",
                    previous_role=access.role,
                    granted_by=None,
                )
                logger.info(f"Доступ {access_id} отозван")

            return result

        except Exception as e:
            logger.error(f"Ошибка отзыва доступа: {e}")
            return False

    async def get_device_accesses(self, device_id: UUID) -> list[DeviceAccess]:
        """Получает список всех доступов к устройству.

        Args:
            device_id: Идентификатор устройства

        Returns:
            Список записей доступа
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.warning("Persistence модуль не имеет device_access")
                return []

            loaded: list[
                DeviceAccess
            ] = await self.persistence.device_access.load_accesses_for_device(device_id)
            return loaded

        except Exception as e:
            logger.error(f"Ошибка получения доступов к устройству {device_id}: {e}")
            return []

    async def get_user_accessible_devices(self, user_id: str) -> list[Device]:
        """Получает все устройства, к которым пользователь имеет доступ.

        Args:
            user_id: Идентификатор пользователя

        Returns:
            Список устройств с доступом
        """
        try:
            if not self.persistence or not hasattr(self.persistence, "device_access"):
                logger.warning("Persistence модуль не имеет device_access")
                return []

            # Получаем все записи доступа пользователя
            user_accesses = await self.persistence.device_access.load_accesses_for_user(user_id)

            # Получаем устройства с доступом
            devices = []
            for access in user_accesses:
                device = await self.get_device(access.device_id)
                if device:
                    devices.append(device)

            logger.debug(f"Пользователь {user_id} имеет доступ к {len(devices)} устройствам")
            return devices

        except Exception as e:
            logger.error(f"Ошибка получения доступных устройств пользователя {user_id}: {e}")
            return []

    # ============ T049-T052: WebSocket синхронизация состояния ============
