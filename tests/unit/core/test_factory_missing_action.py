"""Сломанный шаблон не роняет платформу, но о нём сообщают (фаза 1, T005).

Решение владельца 2026-10-10: **платформа должна быть максимально устойчивой,
но обязана сообщать о любых проблемах**. Обе половины обязательны: устойчивость
без сообщения — это молчаливая поломка, сообщение без устойчивости — платформа,
которая не запускается из-за опечатки в имени действия.

Что было (`research.md` D8): фабрика печатает WARNING, `action_fn` остаётся
`None`, переход проходит как успешный и ничего не выполняет. Дом выглядит
отапливаемым, а обогрев не включается — худший из вариантов.

Что должно быть:

- **устройство со сломанным поведением не регистрируется**, а платформа
  продолжает работать: освещение, исправный климат и всё остальное — в бою;
- **причина называется**: имя действия, имя устройства, что именно не так;
- **сбой заметен в готовности**, а не только в журнале: иначе «устойчивость»
  станет тем же молчанием, что и было.

Обоснование изоляции по устройству, а не по шаблону: два устройства в одной
комнате могут делить шаблон, и ошибка в одном поведении не должна выключать
соседнее.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import copy

from core.definitions import YAMLFSMDefinition
from core.fsm.factory import FSMFactory
from core.models.manifest import (
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


def _registry() -> Registry:
    """Реестр с полным набором условий и действий.

    Returns:
        Готовый реестр.
    """
    from core.action_handlers import register_all_actions
    from core.control_tracker import ControlTracker
    from core.guards.builtin import register_all_guards

    registry = Registry()
    register_all_guards(registry, ControlTracker())
    register_all_actions(registry)
    return registry


def _factory() -> FSMFactory:
    """Фабрика без движка: для проверки разбора определений.

    Returns:
        Фабрика с заполненным реестром.
    """
    return FSMFactory(engine=None, registry=_registry(), event_bus=None)  # type: ignore[arg-type]


def _definition(action: str | None, guard: str | None = None) -> YAMLFSMDefinition:
    """Определение автомата с одним переходом.

    Args:
        action: Имя действия либо None.
        guard: Имя условия либо None.

    Returns:
        Модель определения.
    """
    transition: dict[str, object] = {
        "from_state": "OFF",
        "to_state": "ON",
        "trigger": "temperature_changed",
    }
    if action is not None:
        transition["action"] = action
    if guard is not None:
        transition["guard"] = guard

    return YAMLFSMDefinition.model_validate(
        {
            "entity_id": "switch.obogrevatel_kitchen_climate_control_10",
            "target_device_id": "switch.obogrevatel_kitchen",
            "initial_state": "OFF",
            "states": ["OFF", "ON"],
            "transitions": [transition],
        }
    )


class TestValidationFindsProblems:
    """Проверка называет отсутствующие действия и условия."""

    def test_unknown_action_is_reported(self) -> None:
        """Действие не в реестре попадает в отчёт.

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(_definition("no_such_action"))  # noqa: SLF001

        assert any("no_such_action" in problem for problem in problems), (
            "проверка обязана назвать отсутствующее действие: иначе опечатка в "
            "имени проходит незамеченной"
        )

    def test_unknown_guard_is_reported(self) -> None:
        """Условие не в реестре попадает в отчёт.

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(  # noqa: SLF001
            _definition("heater_timer_on", guard="may_freeze")
        )

        assert any("may_freeze" in problem for problem in problems)

    def test_known_action_passes_validation(self) -> None:
        """Существующее действие проверку проходит.

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(_definition("heater_timer_on"))  # noqa: SLF001

        assert problems == [], f"существующее действие не должно считаться проблемой: {problems}"

    def test_transition_without_action_is_allowed(self) -> None:
        """Переход без действия — законен: так оформляют «ничего не менять».

        Returns:
            Ничего.
        """
        factory = _factory()

        problems = factory._validate_guards_and_actions(_definition(action=None))  # noqa: SLF001

        assert problems == []

    def test_every_problem_is_reported_not_just_the_first(self) -> None:
        """Показываются все проблемы, а не только первая.

        Returns:
            Ничего.
        """
        factory = _factory()
        definition = YAMLFSMDefinition.model_validate(
            {
                "entity_id": "switch.x_climate_control_10",
                "target_device_id": "switch.x",
                "initial_state": "OFF",
                "states": ["OFF", "ON"],
                "transitions": [
                    {
                        "from_state": "OFF",
                        "to_state": "ON",
                        "trigger": "temperature_changed",
                        "action": "first_typo",
                    },
                    {
                        "from_state": "ON",
                        "to_state": "OFF",
                        "trigger": "timeout",
                        "action": "second_typo",
                    },
                ],
            }
        )

        problems = factory._validate_guards_and_actions(definition)  # noqa: SLF001

        assert len(problems) >= 2, (
            f"обе опечатки должны быть названы сразу: чинить по одной — значит "
            f"каждое исправление оборачивается новым перезапуском. Найдено: {problems}"
        )


class TestBrokenBehaviorIsIsolated:
    """Сбой одного поведения не роняет платформу."""

    def test_unknown_action_skips_only_its_behavior(self) -> None:
        """Устройство со сломанным действием не регистрируется, остальные — да.

        Returns:
            Ничего.
        """
        factory = _factory_with_broken_heating()
        manifest = _base_manifest()

        definitions, report = factory.create_from_manifest_reported(manifest)

        registered = {d.target_device_id for d in definitions}
        assert "switch.obogrevatel_spalnia" not in registered, (
            "устройство со сломанным действием не должно регистрироваться: "
            "иначе оно выглядит исправным, а обогрев не работает"
        )
        assert "light.table_lights" in registered, (
            "освещение обязано продолжать работать: сломанный шаблон климата не "
            "должен выключать свет во всём доме"
        )
        assert len(report.skipped) == 1, (
            f"в отчёте должен быть ровно один пропуск: {report.skipped}"
        )

    def test_report_names_device_and_problem(self) -> None:
        """Отчёт называет устройство и суть сбоя.

        Returns:
            Ничего.
        """
        factory = _factory_with_broken_heating()
        manifest = _base_manifest()

        _, report = factory.create_from_manifest_reported(manifest)

        skipped = report.skipped[0]
        assert skipped.device_id == "switch.obogrevatel_spalnia", (
            "без имени устройства искать причину негде: в доме пять обогревателей"
        )
        assert "heater_timer_on" in skipped.reason, (
            f"причина обязана называть опечатку, а не «ошибка загрузки»: {skipped.reason}"
        )

    def test_report_separates_domains(self) -> None:
        """Отчёт различает сломанное и загруженное.

        Returns:
            Ничего.
        """
        factory = _factory_with_broken_heating()
        manifest = _base_manifest()

        _, report = factory.create_from_manifest_reported(manifest)

        assert report.loaded == 1, f"освещение должно быть загружено: {report}"
        assert len(report.skipped) == 1

    def test_healthy_manifest_reports_no_skips(self) -> None:
        """Исправный манифест не даёт пропусков.

        Returns:
            Ничего.
        """
        factory = _factory_with_broken_heating(fix=True)
        manifest = _base_manifest()

        definitions, report = factory.create_from_manifest_reported(manifest)

        assert report.skipped == [], f"исправный манифест не должен ничего пропускать: {report}"
        assert len(definitions) == 2

    def test_report_is_visible_to_readiness(self) -> None:
        """Отчёт попадает в сведения о готовности.

        Returns:
            Ничего.
        """
        factory = _factory_with_broken_heating()
        manifest = _base_manifest()

        _, report = factory.create_from_manifest_reported(manifest)

        assert report.ok is False, (
            "готовность обязана быть не-ок, пока сломанное поведение не "
            "разобрано: устойчивость не должна выглядеть как «всё хорошо»"
        )
        assert report.as_dict()["skipped"], "пропуски обязаны быть видны в сводке готовности"


def _factory_with_broken_heating(fix: bool = False) -> FSMFactory:
    """Фабрика, у которой в шаблоне климата ошибочное имя действия.

    Подмена идёт через кэш экземпляра, а не через класс: кэш принадлежит
    фабрике, и шаблон читается один раз за её жизнь.

    Args:
        fix: Оставить ли существующее имя действия.

    Returns:
        Фабрика с испорченным шаблоном климата и целым шаблоном света.
    """
    factory = _factory()
    wanted = "heater_timer_on" if fix else "heater_timer_on_typo"
    original = factory._load_template("climate_control")  # noqa: SLF001
    patched = copy.deepcopy(original)
    for transition in patched["transitions"]:
        if transition.get("action") == "heater_timer_on":
            transition["action"] = wanted
    factory._template_cache["climate_control"] = patched  # noqa: SLF001
    return factory


def _base_manifest() -> Manifest:
    """Базовый манифест: комната с климатом и комната со светом.

    Returns:
        Модель манифеста.
    """
    from core.models.manifest import BehaviorConfig, DeviceConfig

    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={"temperature": "sensor.datchik_temperatury_spalnia_temperature"},
                devices=[
                    DeviceConfig(
                        id="switch.obogrevatel_spalnia",
                        type="climate",
                        name="Обогреватель спальни",
                        behaviors=[
                            BehaviorConfig(template="climate_control", priority=10, params={})
                        ],
                    )
                ],
            ),
            RoomConfig(
                id="kuhnya",
                name="Кухня",
                sensors={"motion": "binary_sensor.dvizheniia"},
                devices=[
                    DeviceConfig(
                        id="light.table_lights",
                        type="light",
                        name="Свет над столом",
                        behaviors=[BehaviorConfig(template="lighting", priority=10, params={})],
                    )
                ],
            ),
        ],
    )
