"""Действенность параметров поведения проверяется кодом, а не обещанием (#71).

Контракт шаблонов объявляет для каждого параметра `effective: true/false`, и форма
поведения обязана опираться именно на эту метку: иначе пользователю показывают
поля, изменение которых ничего не меняет — тот же класс дефекта, что #65 и #69,
только в интерфейсе.

Проверка двусторонняя:

- параметр с `effective: true` обязан упоминаться в горячем пути (фабрика,
  действия, guard'ы) — иначе метка враньёт;
- параметр с `effective: false` обязан **не** упоминаться там — иначе он рабочий,
  а форма его не покажет.

Второе направление важно: метка `false` без проверки превращается в запрет на
работающую настройку. Именно на этом первая редакция записи #71 ошиблась,
объявив `schedule` инертным: он рабочий, фабрика вешает по нему guard.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "src" / "features" / "CONTRACT.yaml"

HOT_PATH_FILES = (
    "src/core/fsm/factory.py",
    "src/core/action_handlers.py",
    "src/core/guards/builtin.py",
    "src/core/guards/schedule_guard.py",
)
"""Файлы исполняемого пути.

Генератор манифеста и валидатор сюда не входят намеренно: они читают параметр,
чтобы **проверить его форму**, а чтобы он влиял на поведение. Именно на этом
ошиблась первая редакция записи #71, объявив `schedule` инертным.
"""


def _hot_path_mentions(param: str) -> bool:
    """Проверяет, упоминается ли параметр в исполняемом пути.

    Args:
        param: Имя параметра.

    Returns:
        True, если параметр есть хотя бы в одном файле горячего пути.
    """
    needle = f'"{param}"'
    return any(needle in (ROOT / rel).read_text(encoding="utf-8") for rel in HOT_PATH_FILES)


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    """Загруженный контракт шаблонов.

    Returns:
        Разобранный CONTRACT.yaml.
    """
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _declared_params(contract: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Собирает все объявленные параметры.

    Args:
        contract: Контракт шаблонов.

    Returns:
        Список троек «шаблон, параметр, описание».
    """
    return [
        (name, param, meta)
        for name, entry in contract["templates"].items()
        for param, meta in (entry.get("params") or {}).items()
    ]


class TestEffectivenessMatchesCode:
    """Метка действенности обязана совпадать с кодом."""

    def test_should_declare_at_least_one_param(self, contract: dict[str, Any]) -> None:
        """Контракт описывает параметры хотя бы для части шаблонов.

        Args:
            contract: Контракт шаблонов.
        """
        assert _declared_params(contract), "в контракте нет ни одного параметра"

    def test_effective_params_must_be_read_in_hot_path(self, contract: dict[str, Any]) -> None:
        """Помеченный действующим параметр обязан читаться кодом.

        Args:
            contract: Контракт шаблонов.
        """
        for template, param, meta in _declared_params(contract):
            if meta["effective"]:
                assert _hot_path_mentions(param), (
                    f"{template}.{param} помечен действующим, но в исполняемом пути "
                    f"не упоминается — метка врёт, и форма покажет мёртвое поле"
                )

    def test_inert_params_must_not_be_read_in_hot_path(self, contract: dict[str, Any]) -> None:
        """Помеченный инертным параметр обязан быть нерабочим.

        Args:
            contract: Контракт шаблонов.
        """
        for template, param, meta in _declared_params(contract):
            if not meta["effective"]:
                assert not _hot_path_mentions(param), (
                    f"{template}.{param} помечен инертным, но код его читает — "
                    "работающая настройка была бы скрыта от пользователя"
                )

    def test_should_have_type_and_range_for_every_param(self, contract: dict[str, Any]) -> None:
        """У каждого параметра объявлены тип и диапазон — иначе форма не построит поле.

        Args:
            contract: Контракт шаблонов.
        """
        for template, param, meta in _declared_params(contract):
            assert meta.get("type"), f"{template}.{param}: не объявлен тип"
            assert meta.get("range"), f"{template}.{param}: не объявлен диапазон"
            assert meta.get("note"), f"{template}.{param}: нет пояснения для пользователя"


class TestManifestParamsAreCovered:
    """Параметры реального манифеста описаны в контракте."""

    def test_should_cover_params_used_in_deployment_manifest(self) -> None:
        """Каждый параметр из манифеста развёртывания есть в контракте.

        Неописанный параметр — поле, о котором форма не знает: оно молча
        пропадёт при перезаписи.
        """
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        declared = {param for _, param, _ in _declared_params(contract)}

        manifest = yaml.safe_load(
            (ROOT / "deploy" / "docker" / "config" / "manifest.yaml").read_text(encoding="utf-8")
        )
        used = {
            key
            for room in manifest["rooms"]
            for device in (room.get("devices") or [])
            for behavior in (device.get("behaviors") or [])
            for key in (behavior.get("params") or {})
        }
        # Пустое множество — не повод ронять проверку: после перехода на реальный
        # дом параметры задаёт владелец, и на момент прогона их может не быть.
        # Раньше здесь стояло `assert used`: после очистки манифеста и повторного
        # заполнения устройствами без параметров проверка падала на пустом входе,
        # то есть проверяла не покрытие, а факт наличия параметров.
        missing = sorted(used - declared)
        assert not missing, (
            f"параметры манифеста не описаны в контракте: {missing}. Форма их не "
            "покажет, и они молча пропадут при перезаписи поведения."
        )
