"""Режим развёртывания обязан быть виден оператору, а не только в логе.

`SHADOW_MODE` уже читается кодом (`DeploymentManager.from_env` в
`Container.deployment`) и запрет выхода в Home Assistant работает. Но режим
видно только в одной строке журнала при старте: `Режим развёртывания: shadow`.
Ни `/ready`, ни `/health` о нём не сообщают.

Чем это опасно
--------------

Дефект #77 был обратной стороной того же: оператор читал `.env`, видел
`SHADOW_MODE=true` и считал, что платформа не трогает дом — а она трогала.
Теперь зеркальная ситуация: платформа может молча блокировать все команды,
а оператор видит исправную систему — события приходят, автоматы считают
состояния, `/ready` отвечает `ready: true`, и только лампы не включаются.
Причина не видна нигде, кроме строки в логе, пролитой часами назад.

Поэтому режим — часть готовности, а не строчка в журнале. Причём в режиме
тени готовность **ложная**: система не исполняет обещанное.

Что проверяется
---------------

1. В режиме тени `/ready` сообщает, что система не готова исполнять команды,
   и называет режим — оператор должен узнать о нём из ответа, а не из лога.
2. В активном режиме готовность прежняя: система исполняет обещанное.
3. Проверка не должна падать, когда менеджера развёртывания нет (тесты,
   сборка без контейнера) — это отсутствие данных, а не отказ.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.deployment_manager import DeploymentManager, DeploymentMode
from webui.routes import readiness


class _Adapter:
    """Адаптер с установленным соединением — он к режиму отношения не имеет."""

    is_connected = True


def _deployment(mode: DeploymentMode) -> DeploymentManager:
    """Собрать менеджер развёртывания в заданном режиме.

    Args:
        mode: Требуемый режим.

    Returns:
        Инициализированный менеджер.
    """
    manager = DeploymentManager()
    manager.initialize()
    manager.state.mode = mode
    return manager


class _Container:
    """Контейнер с адаптером и менеджером развёртывания."""

    def __init__(self, deployment: DeploymentManager | None) -> None:
        """Создать контейнер.

        Args:
            deployment: Менеджер развёртывания либо None.
        """
        self._adapter = _Adapter()
        self._deployment = deployment
        self._watchdog = None
        self._fsm = None


class _Request:
    """Запрос с контейнером в состоянии приложения."""

    def __init__(self, container: Any) -> None:
        """Создать запрос.

        Args:
            container: Контейнер платформы.
        """

        class _State:
            def __init__(self, value: Any) -> None:
                self.container = value

        class _App:
            def __init__(self, value: Any) -> None:
                self.state = _State(value)

        self.app = _App(container)


class TestShadowModeIsVisible:
    """Режим тени виден в ответе о готовности."""

    def test_shadow_mode_is_reported(self) -> None:
        """Ответ о готовности называет режим.

        Returns:
            Ничего.
        """
        container = _Container(_deployment(DeploymentMode.SHADOW))

        result = readiness.check_deployment_mode(container)

        assert result["mode"] == "shadow", (
            f"режим развёртывания не назван в ответе о готовности: {result}. "
            f"Оператор, который считает систему исправной по `/ready`, не узнает, "
            f"что команды не исполняются"
        )

    def test_shadow_mode_is_not_ready(self) -> None:
        """В режиме тени система не готова исполнять обещанное.

        Returns:
            Ничего.
        """
        container = _Container(_deployment(DeploymentMode.SHADOW))

        result = readiness.check_deployment_mode(container)

        assert result["ok"] is False, (
            f"/ready сообщил готовность при режиме тени: {result}. Платформа "
            f"принимает события и считает состояния, но не выключает свет — "
            f"это выглядит как исправная система"
        )

    def test_active_mode_is_ready(self) -> None:
        """В активном режиме готовность прежняя.

        Returns:
            Ничего.
        """
        container = _Container(_deployment(DeploymentMode.ACTIVE))

        result = readiness.check_deployment_mode(container)

        assert result["ok"] is True, f"активный режим должен быть готов: {result}"
        assert result["mode"] == "active"

    def test_hybrid_mode_executes_actions(self) -> None:
        """Гибридный режим исполняет команды и потому готов.

        Returns:
            Ничего.
        """
        container = _Container(_deployment(DeploymentMode.HYBRID))

        result = readiness.check_deployment_mode(container)

        assert result["ok"] is True, f"гибридный режим исполняет команды: {result}"

    def test_mode_matches_what_gate_actually_decides(self) -> None:
        """Признак в ответе совпадает с решением ворот, а не выдуман отдельно.

        Returns:
            Ничего.
        """
        for mode in DeploymentMode:
            container = _Container(_deployment(mode))

            result = readiness.check_deployment_mode(container)

            assert result["ok"] is mode_should_execute(mode), (
                f"в режиме {mode.value} ворота и ответ о готовности разошлись: "
                f"ворота — {mode_should_execute(mode)}, ответ — {result['ok']}. "
                f"Расхождение означало бы, что `/ready` врёт в другую сторону"
            )

    def test_absent_manager_is_not_a_failure(self) -> None:
        """Отсутствие менеджера — отсутствие данных, а не отказ готовности.

        Returns:
            Ничего.
        """
        result = readiness.check_deployment_mode(_Container(None))

        assert result["ok"] is True, (
            f"сборка без менеджера развёртывания не должна ломать готовность: "
            f"{result}. Иначе тесты и локальный запуск падали бы на проверке, "
            f"которая ничего не проверяет для этой конфигурации"
        )
        assert result.get("mode") == "unknown"

    def test_absent_container_is_reported(self) -> None:
        """Нет контейнера — есть что сказать.

        Returns:
            Ничего.
        """
        result = readiness.check_deployment_mode(None)

        assert result["ok"] is True
        assert result["mode"] == "unknown"


class TestCollectChecksIncludesDeploymentMode:
    """Режим входит в сводку готовности, а не живёт отдельно."""

    def test_summary_contains_the_check(self) -> None:
        """`/ready` включает проверку режима в общий список.

        Returns:
            Ничего.
        """
        container = _Container(_deployment(DeploymentMode.SHADOW))

        checks = readiness.collect_checks(_Request(container))

        assert "deployment_mode" in checks, (
            f"проверка режима не попала в сводку готовности: {sorted(checks)}. "
            f"Проверка, которую никто не зовёт, не защищает ни от чего"
        )
        assert checks["deployment_mode"]["ok"] is False


def mode_should_execute(mode: DeploymentMode) -> bool:
    """Сказать, исполняет ли ворота команды в данном режиме.

    Отдельная функция, а не обращение к воротам в проверке: иначе проверка
    сравнивала бы ответ с тем же источником, из которого он получен, и всегда
    проходила бы.

    Args:
        mode: Режим развёртывания.

    Returns:
        True, если ворота разрешают выход в Home Assistant.
    """
    return mode in (DeploymentMode.ACTIVE, DeploymentMode.HYBRID)
