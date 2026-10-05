"""Контракт шаблонов поведения: документ должен совпадать с кодом (Known Issue #67).

Дефект, который закрывает проверка. Платформа публикует 7 событий
(`EventRouter.SENSOR_EVENT_MAP`), а из них шаблоны слушают **одно** —
`motion_detected`. Остальные шесть, включая `motion_cleared`, приходят в шаблоны,
где для них нет перехода. В обратную сторону: 27 из 28 триггеров, объявленных
шаблонами, не порождаются ничем — часть приходит из движка (`timeout`),
остальные не имеют источника вовсе.

Ни один интерфейс не может честно построить форму поведения по такой картине, а
пользователю нечем объяснить, почему «включение по движению» работает, а
«выключение по движению» нет.

Поэтому контракт вынесен в `src/features/CONTRACT.yaml`, а этот тест сверяет его
с кодом: правка шаблона, реестра или карты событий без перегенерации роняет
прогон. Генератор — `tools/gen_template_contract.py`.

Что тест **не** делает: он не требует, чтобы каждый триггер имел источник. Таких
пробелов много, они перечислены машинно-читаемым полем `unproduced_triggers` и
описаны прозой в `gaps`. Закрытие каждого — отдельная задача; здесь они не
теряются и не замалчиваются.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pathlib
from typing import Any

import yaml

from core.action_handlers import register_all_actions
from core.events.event_router import EventRouter
from core.guards.builtin import REGISTERED_GUARDS
from core.registry import Registry


FEATURES_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "features"
CONTRACT_PATH = FEATURES_DIR / "CONTRACT.yaml"

SOURCE_SENSOR = "sensor"
SOURCE_ENGINE = "engine"
SOURCE_NONE = "НЕТ ПРОИСХОДИТЕЛЯ"
ALLOWED_SOURCES = {SOURCE_SENSOR, SOURCE_ENGINE, SOURCE_NONE}


def _load(path: pathlib.Path) -> Any:
    """Разбирает YAML-файл.

    Args:
        path: Путь к файлу.

    Returns:
        Разобранные данные.
    """
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _templates() -> dict[str, dict[str, Any]]:
    """Читает шаблоны из src/features, кроме контракта.

    Returns:
        Словарь «имя шаблона → разобранный шаблон».
    """
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(FEATURES_DIR.glob("*.yaml")):
        if path.stem == "CONTRACT":
            continue
        result[path.stem] = _load(path)
    return result


def _transitions(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Возвращает переходы шаблона списком.

    Args:
        template: Разобранный шаблон.

    Returns:
        Список переходов.
    """
    transitions = template.get("transitions") or []
    return list(transitions) if isinstance(transitions, list) else []


def _uniq(values: list[str | None]) -> list[str]:
    """Оставляет непустые значения в порядке первого появления.

    Args:
        values: Исходные значения.

    Returns:
        Список уникальных непустых строк.
    """
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _router_events() -> set[str]:
    """Возвращает все события, публикуемые EventRouter.

    Returns:
        Множество имён событий.
    """
    return {event for events in EventRouter.SENSOR_EVENT_MAP.values() for event in events}


def _registered_actions() -> set[str]:
    """Возвращает имена действий, зарегистрированных в реестре.

    Returns:
        Множество имён действий.
    """
    registry = Registry()
    register_all_actions(registry)
    return set(registry.list_actions())


class TestDocumentMatchesCode:
    """Документ обязан совпадать с кодом."""

    def test_contract_parses(self) -> None:
        """Файл контракта разбирается как YAML."""
        assert isinstance(_load(CONTRACT_PATH), dict)

    def test_cover_every_template(self) -> None:
        """Каждый шаблон из src/features описан в контракте."""
        contract = _load(CONTRACT_PATH)
        assert set(contract["templates"]) == set(_templates())

    def test_actions_match_templates(self) -> None:
        """Список действий совпадает с шаблонами."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            actual = _uniq([t.get("action") for t in _transitions(_templates()[name])])
            assert entry["actions"] == actual, (
                f"{name}: контракт {entry['actions']} ≠ шаблон {actual}"
            )

    def test_guards_match_templates(self) -> None:
        """Список guard'ов совпадает с шаблонами."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            actual = _uniq([t.get("guard") for t in _transitions(_templates()[name])])
            assert entry["guards"] == actual, (
                f"{name}: контракт {entry['guards']} ≠ шаблон {actual}"
            )

    def test_triggers_match_templates(self) -> None:
        """Список триггеров совпадает с шаблонами."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            actual = _uniq([t.get("trigger") for t in _transitions(_templates()[name])])
            assert list(entry["triggers"]) == actual, (
                f"{name}: контракт {list(entry['triggers'])} ≠ шаблон {actual}"
            )

    def test_registered_actions_match_registry(self) -> None:
        """Список действий совпадает с реестром."""
        contract = _load(CONTRACT_PATH)
        assert sorted(contract["registered_actions"]) == sorted(_registered_actions())

    def test_registered_guards_match_registry(self) -> None:
        """Список guard'ов совпадает с зарегистрированными."""
        contract = _load(CONTRACT_PATH)
        assert sorted(contract["registered_guards"]) == sorted(REGISTERED_GUARDS)

    def test_sensor_events_match_router(self) -> None:
        """Карта событий совпадает с SENSOR_EVENT_MAP."""
        contract = _load(CONTRACT_PATH)
        assert contract["sensor_events"] == {
            key: list(value) for key, value in EventRouter.SENSOR_EVENT_MAP.items()
        }


class TestProducersAreHonest:
    """Источники событий указаны честно."""

    def test_published_events_are_marked_as_sensor(self) -> None:
        """Событие роутера не может быть помечено «без источника»."""
        contract = _load(CONTRACT_PATH)
        router = _router_events()
        for name, entry in contract["templates"].items():
            for trigger, source in entry["triggers"].items():
                if trigger in router:
                    assert source == SOURCE_SENSOR, (
                        f"{name}.{trigger}: публикуется EventRouter, а указано {source!r}"
                    )

    def test_timeout_is_marked_as_engine(self) -> None:
        """Триггер timeout приходит из движка."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            if "timeout" in entry["triggers"]:
                assert entry["triggers"]["timeout"] == SOURCE_ENGINE, (
                    f"{name}: timeout должен иметь источник {SOURCE_ENGINE!r}"
                )

    def test_only_known_source_labels(self) -> None:
        """Метка источника — из закрытого перечня."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            for trigger, source in entry["triggers"].items():
                assert source in ALLOWED_SOURCES, f"{name}.{trigger}: неизвестная метка {source!r}"

    def test_unproduced_triggers_list_matches_marks(self) -> None:
        """Поле unproduced_triggers совпадает с метками в triggers."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            marked = [t for t, s in entry["triggers"].items() if s == SOURCE_NONE]
            assert entry["unproduced_triggers"] == marked, (
                f"{name}: unproduced_triggers {entry['unproduced_triggers']} ≠ {marked}"
            )

    def test_every_unproduced_trigger_has_a_note(self) -> None:
        """Шаблон с триггерами без источника обязан иметь непустой раздел gaps.

        Первая редакция проверки требовала, чтобы проза упоминала каждый триггер
        поимённо. Это невыполнимо: текст всё равно пришлось бы читать глазами, а
        машина его не проверяет. Машинная часть контракта — поле
        ``unproduced_triggers``, и вот его тест уже сверяет с метками.
        """
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            if not entry["unproduced_triggers"]:
                continue
            assert entry.get("gaps"), f"{name}: есть триггеры без источника, но gaps пуст"

    def test_unheard_platform_event_is_listed(self) -> None:
        """Событие роутера, которое никто не слушает, перечислено в контракте."""
        contract = _load(CONTRACT_PATH)
        listened = {t for entry in contract["templates"].values() for t in entry["triggers"]}
        assert contract["uncovered_platform_events"] == sorted(_router_events() - listened)


class TestReachableTemplates:
    """Достижимые шаблоны обязаны быть исполнимыми."""

    def test_reachable_templates_have_registered_actions(self) -> None:
        """Достижимый шаблон имеет все действия в реестре."""
        contract = _load(CONTRACT_PATH)
        registered = _registered_actions()
        for name, entry in contract["templates"].items():
            if not entry["reachable"]:
                continue
            missing = [a for a in entry["actions"] if a not in registered]
            assert not missing, f"{name} достижим, но действия не в реестре: {missing}"

    def test_reachable_templates_have_registered_guards(self) -> None:
        """Достижимый шаблон имеет все guard'ы зарегистрированными."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            if not entry["reachable"]:
                continue
            missing = [g for g in entry["guards"] if g not in REGISTERED_GUARDS]
            assert not missing, f"{name}: guard'ы не зарегистрированы: {missing}"

    def test_template_with_missing_actions_is_not_reachable(self) -> None:
        """Шаблон без действий в реестре не помечен достижимым."""
        contract = _load(CONTRACT_PATH)
        registered = _registered_actions()
        for name, entry in contract["templates"].items():
            if any(a not in registered for a in entry["actions"]):
                assert entry["reachable"] is False, (
                    f"{name}: действия отсутствуют в реестре, но шаблон помечен достижимым"
                )
                assert not entry["in_manifest"], f"{name}: числится применяемым к дому"

    def test_unreachable_templates_have_no_rooms_listed(self) -> None:
        """Недостижимый шаблон не применяется ни к одной комнате."""
        contract = _load(CONTRACT_PATH)
        for name, entry in contract["templates"].items():
            if not entry["reachable"]:
                assert not entry["in_manifest"], f"{name}: недостижим, но указан в комнатах"
