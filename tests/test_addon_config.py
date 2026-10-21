"""Аддон Home Assistant: обёртка не должна расходиться с платформой (B79).

Аддон — тонкая обёртка вокруг готового образа платформы: Supervisor даёт ему
адрес и токен Home Assistant (`http://supervisor/core`, `SUPERVISOR_TOKEN`), а
`run.sh` переводит опции аддона в переменные окружения платформы. Ничего не
собирается заново, длинного токена нет.

Проверки держат то, что легко сломать незаметно:

* обязательные поля `config.yaml` и совпадение опций со схемой — иначе
  Supervisor отвергнет аддон или не даст его настроить;
* `homeassistant_api: true` и `addon_config` — без них нет ни токена, ни
  сохраняемых данных (и резервных копий);
* `run.sh` берёт адрес и токен у Supervisor и **не** содержит длинного токена;
* Dockerfile собирается поверх образа платформы, а не заново.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ADDON = Path("behavioral_platform")
CONFIG = ADDON / "config.yaml"
RUN = ADDON / "run.sh"
DOCKERFILE = ADDON / "Dockerfile"
REPOSITORY = Path("repository.yaml")


def _yaml(path: Path) -> dict[str, Any]:
    """Прочитать YAML-файл аддона.

    Args:
        path: Путь к файлу.

    Returns:
        Словарь содержимого.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class TestRepository:
    """Репозиторий аддонов описан так, как его ждёт Supervisor."""

    def test_repository_marker_is_complete(self) -> None:
        """Есть имя, адрес и сопровождающий."""
        data = _yaml(REPOSITORY)

        assert data["name"]
        assert data["url"].startswith("https://github.com/")
        assert "@" in data["maintainer"]

    def test_addon_folder_is_present(self) -> None:
        """Аддон лежит отдельным каталогом с конфигурацией."""
        assert CONFIG.exists()
        assert RUN.exists()
        assert DOCKERFILE.exists()


class TestAddonConfig:
    """`config.yaml` проходит требования Supervisor."""

    def test_required_fields(self) -> None:
        """Обязательные поля названы и заполнены."""
        data = _yaml(CONFIG)

        for key in ("name", "version", "slug", "description", "arch", "image"):
            assert data.get(key), f"нет обязательного поля {key}"
        assert data["slug"] == data["slug"].lower().replace("-", "_")
        assert set(data["arch"]) <= {"amd64", "aarch64", "armv7", "i386"}

    def test_image_uses_arch_placeholder(self) -> None:
        """В имени образа есть {arch} — иначе одна архитектура не установится."""
        image = _yaml(CONFIG)["image"]

        assert "{arch}" in image
        assert image.startswith("ghcr.io/")

    def test_api_and_storage(self) -> None:
        """Токен даёт Supervisor, данные живут в addon_config."""
        data = _yaml(CONFIG)

        assert data["homeassistant_api"] is True, "без этого не будет SUPERVISOR_TOKEN"
        assert "addon_config:rw" in data["map"], "конфигурация и данные должны попадать в бэкапы"

    def test_options_match_schema(self) -> None:
        """Каждая опция описана схемой, и наоборот."""
        data = _yaml(CONFIG)

        assert set(data["options"]) == set(data["schema"]), (
            "опции и схема разошлись: Supervisor покажет то, чего нельзя настроить"
        )
        assert data["options"]["log_level"] in {"debug", "info", "warning", "error"}
        assert isinstance(data["options"]["shadow_mode"], bool)

    def test_web_port_and_watchdog(self) -> None:
        """Порт интерфейса объявлен, и Supervisor знает, что считать живым."""
        data = _yaml(CONFIG)

        assert "8125/tcp" in data["ports"]
        assert "8125" in data["watchdog"]


class TestAddonEntrypoint:
    """`run.sh` переводит опции в окружение платформы."""

    def test_supervisor_gives_address_and_token(self) -> None:
        """Адрес и токен — от Supervisor, длинного токена нет."""
        text = RUN.read_text(encoding="utf-8")

        assert "http://supervisor/core" in text
        assert "ws://supervisor/core/websocket" in text
        assert "SUPERVISOR_TOKEN" in text
        assert "eyJ" not in text, "в аддоне не должно быть длинного токена"

    def test_config_and_data_are_persistent(self) -> None:
        """Манифест и данные — в addon_config, а не в слое контейнера."""
        text = RUN.read_text(encoding="utf-8")

        assert "/addon_config/config" in text
        assert "/addon_config/data" in text

    def test_platform_entrypoint_is_reused(self) -> None:
        """Запуск идёт штатной точкой входа образа — без второй сборки."""
        text = RUN.read_text(encoding="utf-8")

        assert "docker-entrypoint.sh" in text
        assert 'exec /app/deploy/docker/docker-entrypoint.sh "$@"' in text


class TestAddonImage:
    """Аддон собирается поверх образа платформы."""

    def test_base_image_is_the_platform(self) -> None:
        """FROM — опубликованный образ платформы с версией сборки."""
        text = DOCKERFILE.read_text(encoding="utf-8")

        assert "FROM ghcr.io/alkamenos/smart-home-platform:${BUILD_VERSION}" in text
        assert 'ENTRYPOINT ["/run.sh"]' in text
