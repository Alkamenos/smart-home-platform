"""Guard'ы и действия, которых требует манифест, но которых нет в коде.

Шаг 0 варианта (а) продакшен-очереди.

Факт, который всё объясняет: при каждом старте платформы в логах идут
`Guard 'is_day_time' not found in registry` и `Action 'climate_heat' not found in
registry`. Сверка шаблонов `src/features/*.yaml` с реестром даёт:

- манифесту нужны **4 guard'а**: `humidity_above_60`, `humidity_below_60`,
  `is_day_time`, `is_manual_override_enabled` — зарегистрирован **ноль**;
- манифесту нужны **10 действий**, из них зарегистрировано 5, не хватает 5:
  `climate_heat`, `climate_cool`, `climate_off`, `fan_turn_on`, `fan_turn_off`.

То есть добавление реального устройства сейчас бесполезно: для освещения guard
отклонит переход, для климата и вентиляции не найдётся действие.

Проверяется поведение, а не факт регистрации: отсутствие обработчика должно
ломать переход, а не молча пропускать его.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from core.action_handlers import (
    climate_cool,
    climate_heat,
    climate_off,
    fan_turn_off,
    fan_turn_on,
)
from core.guards.builtin import (
    make_humidity_above,
    make_humidity_below,
    make_is_day_time,
    make_is_manual_override_enabled,
)


class _ControlTracker:
    """Трекер ручного вмешательства с управляемым ответом."""

    def __init__(self, recent: bool = False) -> None:
        self._recent = recent
        self.calls: list[tuple[str, int]] = []

    def was_manual_within(self, device_id: str, minutes: int) -> bool:
        self.calls.append((device_id, minutes))
        return self._recent


class TestIsDayTime:
    """`is_day_time` — для перехода в режим движения только днём."""

    def test_true_inside_day_range(self) -> None:
        """Днём переход разрешён."""
        guard = make_is_day_time(
            "07:00-23:00", now=lambda: datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
        )

        assert guard(None, {}) is True

    def test_false_at_night(self) -> None:
        """Ночью переход запрещён."""
        guard = make_is_day_time("07:00-23:00", now=lambda: datetime(2026, 10, 5, 2, 0, tzinfo=UTC))

        assert guard(None, {}) is False

    def test_boundaries_are_inclusive(self) -> None:
        """Границы диапазона входят в него."""
        at_start = make_is_day_time(
            "07:00-23:00", now=lambda: datetime(2026, 10, 5, 7, 0, tzinfo=UTC)
        )
        at_end = make_is_day_time(
            "07:00-23:00", now=lambda: datetime(2026, 10, 5, 23, 0, tzinfo=UTC)
        )

        assert at_start(None, {}) is True
        assert at_end(None, {}) is True

    def test_malformed_range_fails_closed(self) -> None:
        """Некорректный диапазон запрещает переход, а не разрешает.

        Ошибка конфигурации обязана вести к отказу: разрешить переход при
        непонятном «дне» значит включить свет ночью.
        """
        guard = make_is_day_time("не-время", now=lambda: datetime(2026, 10, 5, 14, 0, tzinfo=UTC))

        assert guard(None, {}) is False


class TestHumidityGuards:
    """Порог влажности берётся из параметров, а не из имени guard'а."""

    def test_above_uses_configured_threshold(self) -> None:
        """Порог из параметров важнее числа в имени."""
        guard = make_humidity_above()
        context = {"humidity": 70, "humidity_threshold": 65}

        assert guard(None, context) is True

    def test_above_false_below_threshold(self) -> None:
        """Ниже порога переход запрещён."""
        guard = make_humidity_above()

        assert guard(None, {"humidity": 50, "humidity_threshold": 65}) is False

    def test_falls_back_to_60_without_parameter(self) -> None:
        """Без параметра берётся 60 — как и обещает имя guard'а."""
        guard = make_humidity_above()

        assert guard(None, {"humidity": 61}) is True
        assert guard(None, {"humidity": 59}) is False

    def test_below_is_inverse(self) -> None:
        """Нижний guard' противоположен верхнему."""
        guard = make_humidity_below()

        assert guard(None, {"humidity": 50, "humidity_threshold": 65}) is True
        assert guard(None, {"humidity": 70, "humidity_threshold": 65}) is False

    def test_missing_humidity_fails_closed(self) -> None:
        """Нет данных о влажности — переход запрещён.

        Разрешить вентиляцию без причины хуже, чем не включить её: при
        отсутствующем датчике включение выглядит как ложное срабатывание.
        """
        guard = make_humidity_above()

        assert guard(None, {}) is False


class TestIsManualOverrideEnabled:
    """`is_manual_override_enabled` — автоматике можно вмешаться."""

    def test_allowed_when_no_recent_manual_control(self) -> None:
        """Недавнего ручного вмешательства нет — вмешательство разрешено."""
        tracker = _ControlTracker(recent=False)
        guard = make_is_manual_override_enabled(tracker, lockout_minutes=60)

        assert guard(None, {"entity_id": "light.kitchen"}) is True

    def test_denied_after_manual_control(self) -> None:
        """После ручного управления автоматика не вмешивается."""
        tracker = _ControlTracker(recent=True)
        guard = make_is_manual_override_enabled(tracker, lockout_minutes=60)

        assert guard(None, {"entity_id": "light.kitchen"}) is False

    def test_uses_device_id_from_context(self) -> None:
        """Трекер спрашивается про то устройство, чей автомат сработал."""
        tracker = _ControlTracker(recent=False)
        guard = make_is_manual_override_enabled(tracker, lockout_minutes=45)

        guard(None, {"entity_id": "fan.bathroom"})

        assert tracker.calls == [("fan.bathroom", 45)]

    def test_without_device_id_denied(self) -> None:
        """Без идентификатора устройства решения принять нельзя."""
        tracker = _ControlTracker(recent=False)
        guard = make_is_manual_override_enabled(tracker, lockout_minutes=60)

        assert guard(None, {}) is False


class TestClimateAndFanActions:
    """Новые действия должны строить те же CommandIntent, что и существующие."""

    @pytest.mark.parametrize(
        ("handler", "service"),
        [
            (climate_heat, "set_temperature"),
            (climate_cool, "set_temperature"),
            (climate_off, "turn_off"),
            (fan_turn_on, "turn_on"),
            (fan_turn_off, "turn_off"),
        ],
    )
    def test_builds_intent_for_right_domain(self, handler: Any, service: str) -> None:
        """Каждое действие адресует свою домену и свою услугу."""
        context = {"entity_id": "climate.kitchen", "target_temperature": 22}

        intent = handler(None, context)

        assert intent is not None, f"{handler.__name__} не построил команду"
        assert intent.service == service

    @pytest.mark.parametrize(
        "handler", [climate_heat, climate_cool, climate_off, fan_turn_on, fan_turn_off]
    )
    def test_without_entity_id_returns_none(self, handler: Any) -> None:
        """Без устройства команда не строится, а не отправляется в пустоту."""
        assert handler(None, {}) is None

    def test_climate_carries_target_temperature(self) -> None:
        """Температура из параметров попадает в команду."""
        context = {"entity_id": "climate.kitchen", "target_temperature": 22}

        intent = climate_heat(None, context)

        assert intent is not None
        assert intent.data.get("temperature") == 22, (
            f"температура из параметров поведения потеряна: {intent.data}"
        )

    def test_actions_use_domain_of_device(self) -> None:
        """Домена соответствует типу устройства, а не захардкожена."""
        climate = climate_heat(None, {"entity_id": "climate.kitchen", "target_temperature": 22})
        fan = fan_turn_on(None, {"entity_id": "fan.bathroom"})

        assert climate is not None and climate.domain == "climate"
        assert fan is not None and fan.domain == "fan"


class TestGuardsAreActuallyWired:
    """Guard'ы должны быть в реестре движка, а не просто существовать в модуле.

    Первая версия проверки смотрела только на наличие функций в модуле, и
    инъекция «отключить регистрацию» проходила незамеченной: 27 тестов зелёные
    при полностью отключённых guard'ах. Проверяется свойство, которое важно на
    практике — движок может найти guard'а по имени из шаблона.
    """

    def test_container_registry_has_every_manifest_guard(self) -> None:
        """Реестр контейнера содержит все guard'ы манифеста."""
        from core.container import Container

        container = Container()
        registry = container.registry

        for name in ("is_day_time", "is_manual_override_enabled"):
            assert registry.has_guard(name), (
                f"guard `{name}` есть в коде, но не зарегистрирован: движок "
                "отклонит каждый переход с этим guard'ом"
            )

    def test_registered_guard_is_callable(self) -> None:
        """Зарегистрированный guard вызывается движком как функция."""
        from core.container import Container

        registry = Container().registry
        guard = registry.get_guard("is_day_time")

        assert guard is not None
        assert isinstance(guard(None, {}), bool), (
            f"guard вернул {type(guard(None, {}))}, а движок ждёт булево значение"
        )

    def test_actions_are_registered_in_container(self) -> None:
        """Новые действия доступны движку по имени."""
        from core.container import Container

        registry = Container().registry

        for name in (
            "turn_on_light",
            "turn_off_light",
            "climate_heat",
            "climate_cool",
            "climate_off",
            "fan_turn_on",
            "fan_turn_off",
        ):
            assert registry.get_action(name) is not None, (
                f"действие `{name}` не зарегистрировано: переход будет отклонён"
            )

    def test_every_guard_in_templates_is_registered(self) -> None:
        """Ни один guard из шаблонов не остаётся незарегистрированным.

        Сверка по всем файлам `src/features/*.yaml`, а не по манифесту: иначе
        добавление шаблона с новым guard'ом снова даст молчащие переходы.
        """
        from pathlib import Path

        import yaml

        from core.container import Container

        registry = Container().registry
        needed: set[str] = set()
        for template in Path("src/features").glob("*.yaml"):
            document = yaml.safe_load(template.read_text(encoding="utf-8")) or {}
            for transition in document.get("transitions") or []:
                if transition.get("guard"):
                    needed.add(transition["guard"])

        missing = sorted(name for name in needed if not registry.has_guard(name))
        assert not missing, (
            f"guard'ы из шаблонов не зарегистрированы: {missing}. "
            "Каждый такой guard отклоняет переход в движке."
        )


def _manifest_guard_actions() -> tuple[set[str], set[str]]:
    """Собрать guard'ы и действия, которые требует текущий манифест.

    Читаются настоящие файлы, а не зашитый список: иначе проверка подтверждала
    бы сама себя, а добавление устройства в манифест снова дало бы молчащие
    переходы.
    """
    from pathlib import Path

    import yaml

    manifest = yaml.safe_load(Path("instances/leonids_house/manifest.yaml").read_text("utf-8"))
    guards: set[str] = set()
    actions: set[str] = set()
    for room in manifest.get("rooms") or []:
        for device in room.get("devices") or []:
            for behavior in device.get("behaviors") or []:
                template = yaml.safe_load(
                    Path(f"src/features/{behavior['template']}.yaml").read_text("utf-8")
                )
                for transition in template.get("transitions") or []:
                    if transition.get("guard"):
                        guards.add(transition["guard"])
                    if transition.get("action"):
                        actions.add(transition["action"])
    return guards, actions


class TestManifestRequirementsAreMet:
    """Сверка: всё, что требует манифест, должно быть и написано, и зарегистрировано."""

    def test_manifest_guards_have_implementations(self) -> None:
        """Каждый guard манифеста реализован в коде."""
        import core.guards.builtin as builtin

        guards, _ = _manifest_guard_actions()

        # `may_turn_on` пришёл на смену `is_day_time` в шаблоне света: «сейчас
        # день» отвечало на вопрос по часам контейнера и не знало ни про часовой
        # пояс дома, ни про комнаты, где ночью свет нужен. `is_day_time` в шаблонах
        # больше не встречается, но остаётся зарегистрированным — на него
        # ссылаются внешние описания.
        #
        # `modifier_is_on` появился с ночником (2026-10-09): его включение
        # обусловлено модификатором «мы спим», а не одним движением — иначе
        # ночник зажигался днём.
        # `may_heat` и `may_stop_heating` — составные условия климата: движок
        # допускает на переход одно имя guard'а, а решение «греть» требует трёх
        # проверок (право владельца, чужой термостат, замер температуры).
        assert guards == {
            "humidity_above_60",
            "humidity_below_60",
            "is_manual_override_enabled",
            "may_heat",
            "may_stop_heating",
            "may_turn_on",
            "modifier_is_on",
        }, f"состав нужных guard'ов изменился: {sorted(guards)}"

        factories = {
            "humidity_above_60": "make_humidity_above",
            "humidity_below_60": "make_humidity_below",
            "is_day_time": "make_is_day_time",
            "is_manual_override_enabled": "make_is_manual_override_enabled",
            "may_turn_on": "make_may_turn_on",
            "modifier_is_on": "make_modifier_is_on",
            "may_heat": "make_may_heat",
            "may_stop_heating": "make_may_stop_heating",
        }
        for name in guards:
            assert hasattr(builtin, factories[name]), f"для `{name}` нет реализации"

    def test_all_manifest_actions_are_registered(self) -> None:
        """Каждое действие из шаблонов манифеста есть в реестре обработчиков."""
        from core.action_handlers import ACTION_HANDLERS

        _, actions = _manifest_guard_actions()

        missing = sorted(actions - set(ACTION_HANDLERS))
        assert not missing, f"действия манифеста не зарегистрированы: {missing}"
