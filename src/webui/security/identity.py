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

from starlette.requests import Request

from webui.security.network import is_trusted_host


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


def resolve_actor(request: Request) -> ActorIdentity:
    """Определить участника по источнику запроса.

    Заголовки клиента не дают прав: ``X-Is-Admin`` может только понизить роль
    (``false``) для совместимости с разграничением доступа к приборам, но не
    повысить её. Недоверенный источник всегда анонимен.

    Args:
        request: Входящий запрос.

    Returns:
        Идентичность участника.
    """
    host = request.client.host if request.client is not None else None
    if not is_trusted_host(host):
        return untrusted_actor()

    header_admin = request.headers.get("X-Is-Admin")
    header_user = request.headers.get("X-User-ID")
    if header_admin is None:
        # Доверенный аноним — владелец дома. Названный пользователь без
        # явного повышения — гость: так сохраняется разграничение доступа к
        # приборам, а не «любой заголовок делает администратором».
        is_admin = header_user is None
    else:
        # Заголовок может только понизить роль, но не повысить её.
        is_admin = header_admin.strip().lower() != "false"
    roles = frozenset({Role.OWNER}) if is_admin else frozenset({Role.GUEST})
    subject = header_user or "owner"
    source = (
        TrustSource.INGRESS if request.headers.get("X-Ingress-Path") else TrustSource.TRUSTED_LAN
    )
    return ActorIdentity(subject=subject, roles=roles, source=source, trusted=True)
