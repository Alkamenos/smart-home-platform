"""Доверенные сети управления (спека 018, D2).

Пароль приложения не вводится: граница доверия проходит по сети и ingress.
Список задаётся переменной ``TRUSTED_MANAGEMENT_CIDRS``; по умолчанию —
loopback и частные диапазоны. Точное имя хоста допускается для тестового
транспорта, не для боевого.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any


ENV_TRUSTED_CIDRS = "TRUSTED_MANAGEMENT_CIDRS"

#: Loopback и частные диапазоны: домашняя сеть по умолчанию.
DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


def trusted_entries() -> tuple[Any, ...]:
    """Прочитать настроенные доверенные сети и хосты.

    Returns:
        Кортеж объектов ``ip_network`` либо точных имён хостов.
    """
    raw = os.environ.get(ENV_TRUSTED_CIDRS, DEFAULT_TRUSTED)
    entries: list[Any] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            entries.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            entries.append(value)
    return tuple(entries)


def is_trusted_host(host: str | None) -> bool:
    """Входит ли адрес в доверенную сеть.

    Args:
        host: Адрес клиента из ASGI-запроса.

    Returns:
        True, если источник доверенный.
    """
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Не-IP встречается только в тестовом транспорте; в бою адрес — IP.
        return host in trusted_entries()
    for entry in trusted_entries():
        if isinstance(entry, str):
            continue
        if address in entry:
            return True
    return False
