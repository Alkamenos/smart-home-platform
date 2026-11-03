"""Образ и compose: минимальные права и закреплённые базы (спека 018, US3).

Проверяется текст конфигурации, а не «соберётся ли»: сборка в CI и так есть.
Правила простые и ломаются молча, если их не закрепить тестом.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path


DOCKERFILE = Path("deploy/docker/Dockerfile")
COMPOSE = Path("deploy/docker/docker-compose.prod.yml")
ENTRYPOINT = Path("deploy/docker/docker-entrypoint.sh")


def _text(path: Path) -> str:
    """Прочитать файл.

    Args:
        path: Путь.

    Returns:
        Содержимое.
    """
    return path.read_text(encoding="utf-8")


def test_base_images_are_pinned_by_digest() -> None:
    """Базовые образы не плавают по тегу."""
    dockerfile = _text(DOCKERFILE)
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]

    assert from_lines, "в Dockerfile нет ни одного FROM"
    for line in from_lines:
        assert "@sha256:" in line, (
            f"базовый образ не закреплён по digest: {line!r}. Тег может смениться между сборками"
        )


def test_runtime_does_not_run_as_root() -> None:
    """Процесс приложения работает от непривилегированного пользователя."""
    dockerfile = _text(DOCKERFILE)
    entrypoint = _text(ENTRYPOINT)

    assert "useradd --uid 10001" in dockerfile, "в образе нет непривилегированного пользователя"
    assert "setpriv --reuid=10001" in entrypoint, "entrypoint не сбрасывает права до UID 10001"


def test_runtime_has_no_build_toolchain() -> None:
    """Компиляторы не остаются в runtime-слое."""
    dockerfile = _text(DOCKERFILE)
    runtime = dockerfile.split("FROM python:3.12-slim", 1)[-1]

    for package in ("gcc", "libffi-dev"):
        assert package not in runtime, (
            f"сборочный пакет {package} остался в runtime-слое: лишняя поверхность атаки"
        )


def test_compose_drops_privileges_and_limits_resources() -> None:
    """Compose ограничивает права и ресурсы контейнера."""
    compose = _text(COMPOSE)

    for expected in (
        "read_only: true",
        "cap_drop:",
        "- ALL",
        "no-new-privileges:true",
        "tmpfs:",
    ):
        assert expected in compose, f"в compose нет {expected!r}"

    assert "mem_limit:" in compose or "memory:" in compose, "нет лимита памяти"
    assert "cpus:" in compose, "нет лимита CPU"


def test_entrypoint_drops_privileges() -> None:
    """Compose/image не оставляют процесс приложения root."""
    entrypoint = _text(ENTRYPOINT)

    assert "setpriv --reuid=10001 --regid=10001" in entrypoint, (
        "entrypoint не сбрасывает права до непривилегированного UID"
    )
