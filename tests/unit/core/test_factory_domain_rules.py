"""Доменные правила доезжают до климата и вентиляции (фаза 1, T004).

Молчаливый разрыв в фабрике (`research.md` D3): `factory.py:336` сопоставляет имя
шаблона с именем домена строковым `getattr`:

```python
domain_rules = getattr(automation_rules, behavior.template, None)
```

Имя шаблона `climate_control` не совпадает с именем домена `climate`, поэтому
`domain_rules` всегда `None`, и блок переноса доменных значений в параметры
поведения не выполняется **никогда**. Работает только `lighting`, где имена
случайно совпали.

Опасность класса молчаливых отказов: доменная настройка задаётся в манифесте,
файл валидируется без ошибок, платформа стартует — а правило не применяется.
Владелец видит «настроил и не работает» без единого сообщения.

Тест проверяет, что имя шаблона, не совпадающее с именем домена, всё равно
получает правила.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from core.fsm.factory import _domain_rules_for_template
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
)


def _rules() -> AutomationRules:
    """Правила дома с заполненными доменами климата и вентиляции.

    Returns:
        Модель правил автоматизации.
    """
    return AutomationRules.model_validate(
        {
            "time_zone": "Asia/Yekaterinburg",
            "lighting": {
                "quiet_from": "23:00",
                "quiet_to": "06:30",
                "night_motion_rooms": ["sanuzel"],
                "always_on_motion_rooms": ["sanuzel", "konteiner"],
            },
            "climate": {
                "setpoint_min": 5.0,
                "setpoint_max": 30.0,
            },
            "ventilation": {
                "manual_lockout_min": 15,
            },
        }
    )


class TestTemplateToDomainMapping:
    """Имя шаблона сопоставляется с доменом явно, а не сравнением строк."""

    def test_lighting_still_resolves(self) -> None:
        """Освещение не ломается: правила доезжают как раньше.

        Returns:
            Ничего.
        """
        rules = _rules()

        assert _domain_rules_for_template(rules, "lighting") is rules.lighting, (
            "освещение работает годами: сопоставление правок не должно его сломать"
        )

    def test_climate_template_resolves_to_climate_domain(self) -> None:
        """Шаблон `climate_control` получает правила домена `climate`.

        Returns:
            Ничего.
        """
        rules = _rules()

        resolved = _domain_rules_for_template(rules, "climate_control")

        assert resolved is rules.climate, (
            "шаблон называется climate_control, домен — climate: при сравнении "
            "строк getattr даёт None, и доменные правила климата не применяются "
            "никогда, хотя манифест загружается без ошибок"
        )

    def test_ventilation_template_resolves_to_ventilation_domain(self) -> None:
        """Шаблон `humidity_ventilation` получает правила домена `ventilation`.

        Returns:
            Ничего.
        """
        rules = _rules()

        resolved = _domain_rules_for_template(rules, "humidity_ventilation")

        assert resolved is rules.ventilation, (
            "без этого вентиляция не знает срок ручной блокировки, и "
            "платформа перебивает ручное вмешательство"
        )

    def test_new_ventilation_template_resolves(self) -> None:
        """Новый шаблон `ventilation_modes` тоже получает правила.

        Returns:
            Ничего.
        """
        rules = _rules()

        assert _domain_rules_for_template(rules, "ventilation_modes") is rules.ventilation, (
            "новый шаблон вентиляции обязан получать доменные правила: иначе "
            "придётся дублировать их в каждом устройстве"
        )

    def test_unknown_template_returns_none(self) -> None:
        """Неизвестный шаблон не получает чужих правил.

        Returns:
            Ничего.
        """
        rules = _rules()

        assert _domain_rules_for_template(rules, "no_such_template") is None


class TestDomainDefaultsReachParams:
    """Доменные значения попадают в параметры поведения."""

    def test_climate_defaults_are_applied(self) -> None:
        """Границы уставки доезжают в параметры поведения климата.

        Returns:
            Ничего.
        """
        rules = _rules()
        behavior = BehaviorConfig(template="climate_control", priority=10, params={})

        merged = _apply_domain_defaults(behavior, rules)

        assert merged.params["setpoint_min"] == 5.0, (
            "границы уставки задаются в правилах дома и обязаны доехать до "
            "поведения: иначе проверка FR-034 работает с нулями"
        )
        assert merged.params["setpoint_max"] == 30.0

    def test_explicit_param_wins_over_domain_default(self) -> None:
        """Явный параметр устройства главнее доменного значения.

        Returns:
            Ничего.
        """
        rules = _rules()
        behavior = BehaviorConfig(
            template="climate_control", priority=10, params={"setpoint_min": 10.0}
        )

        merged = _apply_domain_defaults(behavior, rules)

        assert merged.params["setpoint_min"] == 10.0, (
            "явный параметр устройства главнее доменного: обратный порядок "
            "молча перетирал бы настройку, которую задал владелец"
        )

    def test_time_zone_reaches_every_domain(self) -> None:
        """Часовой пояс дома доезжает и до климата, и до вентиляции.

        Returns:
            Ничего.
        """
        rules = _rules()

        climate = _apply_domain_defaults(
            BehaviorConfig(template="climate_control", priority=10, params={}), rules
        )
        ventilation = _apply_domain_defaults(
            BehaviorConfig(template="ventilation_modes", priority=10, params={}), rules
        )

        assert climate.params["time_zone"] == "Asia/Yekaterinburg"
        assert ventilation.params["time_zone"] == "Asia/Yekaterinburg", (
            "контейнер живёт в UTC, дом — в своём поясе: без пояса ночные "
            "окна считаются в часах контейнера"
        )


def _apply_domain_defaults(behavior: BehaviorConfig, rules: AutomationRules) -> BehaviorConfig:
    """Перенести доменные значения в параметры поведения.

    Args:
        behavior: Поведение из манифеста.
        rules: Правила дома.

    Returns:
        Поведение с дополненными параметрами.
    """
    from core.fsm.factory import _apply_domain_rules_to_behavior

    return _apply_domain_rules_to_behavior(behavior, rules)
