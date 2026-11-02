"""Идентичность участника по доверенному источнику (спека 018, D2).

Пароль приложения не вводится (решение владельца 02.11.2026): доверие к
прямому LAN-доступу обеспечивается сетью. Заголовки, присланные клиентом, не
повышают права — роль выводится только из проверенного источника.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Роль участника."""

    OWNER = "owner"
    GUEST = "guest"
    AUTOMATION = "automation"
    MONITOR = "monitor"


class TrustSource(StrEnum):
    """Проверенный источник запроса."""

    TRUSTED_LAN = "trusted_lan"
    INGRESS = "ingress"
    TOKEN = "token"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class ActorIdentity:
    """Подтверждённый участник операции.

    Attributes:
        subject: Отображаемое имя; не используется для авторизации.
        roles: Роли участника.
        source: Проверенный источник.
        trusted: Признак доверия, выставленный сервером.
    """

    subject: str
    roles: frozenset[Role]
    source: TrustSource
    trusted: bool

    @property
    def is_owner(self) -> bool:
        """Может ли участник менять дом.

        Returns:
            True, если роль владельца присутствует и источник доверенный.
        """
        return self.trusted and Role.OWNER in self.roles

    @property
    def can_view(self) -> bool:
        """Может ли участник читать состояние дома.

        Returns:
            True для любой доверенной роли.
        """
        return self.trusted and bool(self.roles)


def untrusted_actor() -> ActorIdentity:
    """Участник по умолчанию для недоверенного запроса.

    Returns:
        Идентичность без ролей и без доверия.
    """
    return ActorIdentity(
        subject="anonymous",
        roles=frozenset(),
        source=TrustSource.UNTRUSTED,
        trusted=False,
    )


def owner_actor(subject: str, source: TrustSource = TrustSource.TRUSTED_LAN) -> ActorIdentity:
    """Участник-владелец для доверенного источника.

    Args:
        subject: Отображаемое имя.
        source: Проверенный источник.

    Returns:
        Идентичность владельца.
    """
    return ActorIdentity(
        subject=subject or "owner",
        roles=frozenset({Role.OWNER}),
        source=source,
        trusted=True,
    )
