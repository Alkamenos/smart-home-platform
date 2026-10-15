"""Настройки, которые обещают и действуют (аудит 2026-10-16, К-10 и К-15).

Два случая одного класса — «объявлено, но не работает»:

* посредник ручного вмешательства обещал настраиваемый перечень ручных
  источников, но поля не было ни в ядре, ни в модели веб-слоя: pydantic молча
  выбрасывал ключ, и задать свой источник было нельзя (К-10);
* заброшенное условие `stops_on_sunrise` оставалось в реестре и **всегда
  отвечало «да»**: ссылка на него в шаблоне молча пропустила бы переход — тот
  самый боевой дефект с гирляндой, из-за которого условие убрали (К-15).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.guards.builtin import make_stops_on_sunrise
from core.models.manifest import AutomationRules


class TestManualCommandSourcesAreConfigurable:
    """Свой источник ручных команд можно задать из манифеста."""

    def test_core_model_keeps_the_house_list(self) -> None:
        """Ядро сохраняет список источников дома.

        Returns:
            Ничего.
        """
        rules = AutomationRules.model_validate(
            {"global_manual_lockout_min": 30, "manual_command_sources": ["telegram"]}
        )

        assert rules.manual_command_sources == ["telegram"], (
            "pydantic молча выбросил ключ: задать свой источник нельзя"
        )

    def test_web_model_keeps_the_house_list(self) -> None:
        """Модель веб-слоя тоже — иначе редактор манифеста его вычеркнет.

        Returns:
            Ничего.
        """
        import sys

        sys.path.insert(0, "src")
        from webui.models import AutomationRules as WebRules

        rules = WebRules.model_validate({"manual_command_sources": ["telegram"]})

        assert rules.manual_command_sources == ["telegram"]

    def test_middleware_honours_the_house_list(self) -> None:
        """Посредник считает ручным источник из списка дома.

        Returns:
            Ничего.
        """
        rules = AutomationRules.model_validate({"manual_command_sources": ["telegram"]})
        middleware = ManualLockoutMiddleware(
            automation_rules=rules, control_tracker=ControlTracker()
        )

        assert middleware._is_manual_source("telegram"), (  # noqa: SLF001 — проверка перечня
            "обещанный настраиваемый перечень остался зашитым"
        )


class TestDeprecatedGuardRefuses:
    """Заброшенное условие не пропускает переход."""

    def test_stops_on_sunrise_refuses(self) -> None:
        """`stops_on_sunrise` отвечает отказом, а не «да».

        Returns:
            Ничего.
        """
        guard = make_stops_on_sunrise()

        assert guard(None, {}) is False, (
            "заброшенное условие разрешает переход: ссылка на него вернула бы "
            "боевой дефект с гирляндой, горящей весь день"
        )
