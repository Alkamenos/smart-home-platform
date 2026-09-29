"""Healthcheck-модуль контейнера (FR-001, FR-002 спецификации 003).

Вызывается Docker healthcheck-ом:

    python -m src.cli.health_check

Выполняет одну HTTP-пробу ``GET /health`` на локальном сервере платформы
и завершается с exit-кодом 0 (сервис готов) либо 1 (недоступность,
таймаут или не-200). Порт читается из переменной окружения ``WEBUI_PORT``
(дефолт 8125 — см. ``src/main.py``). Контракт:
``contracts/operational-contracts.md`` §1.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping


DEFAULT_PORT = "8125"
DEFAULT_TIMEOUT = 5.0


def build_url(environ: Mapping[str, str] | None = None) -> str:
    """Собрать URL пробы healthcheck.

    Args:
        environ: Окружение для чтения WEBUI_PORT (по умолчанию ``os.environ``).

    Returns:
        URL вида ``http://127.0.0.1:{port}/health``.
    """
    env = os.environ if environ is None else environ
    port = env.get("WEBUI_PORT") or DEFAULT_PORT
    return f"http://127.0.0.1:{port}/health"


def probe(url: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Выполнить HTTP-пробу и проверить, что вернулся 200.

    Args:
        url: URL эндпоинта healthcheck.
        timeout: Таймаут ответа в секундах.

    Returns:
        ``True``, если сервер ответил кодом 200; иначе ``False``.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return response.status == 200
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def run_health_check(timeout: float = DEFAULT_TIMEOUT) -> int:
    """Выполнить healthcheck и вернуть exit-код.

    Args:
        timeout: Таймаут пробы в секундах.

    Returns:
        0 — сервис готов; 1 — проба не прошла.
    """
    url = build_url()
    ok = probe(url, timeout=timeout)
    if ok:
        print(f"healthy: {url}")
        return 0
    print(f"unhealthy: probe failed for {url} (timeout={timeout}s)")
    return 1


def main() -> int:
    """Точка входа модуля (``python -m src.cli.health_check``).

    Returns:
        Exit-код процесса.
    """
    return run_health_check()


if __name__ == "__main__":
    sys.exit(main())
